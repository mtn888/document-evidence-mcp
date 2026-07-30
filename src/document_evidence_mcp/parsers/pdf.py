from __future__ import annotations

import tempfile
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from typing import Any

from document_evidence_mcp.chunking import chunk_text, normalize_text
from document_evidence_mcp.models import BBox, EvidenceDraft, ParseResult
from document_evidence_mcp.parsers.base import ParseContext


@lru_cache(maxsize=1)
def load_pymupdf() -> Any:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF could not load its native extension. On Windows, install the "
            "Microsoft Visual C++ Redistributable and place the virtual environment "
            "on a local drive instead of a UNC/network share."
        ) from exc
    return pymupdf


class PdfParser:
    name = "pymupdf"
    version = version("PyMuPDF")
    extensions = frozenset({".pdf"})
    minimum_native_chars = 24

    @staticmethod
    def _is_structurally_blank(page: Any) -> bool:
        if page.get_text("text").strip():
            return False
        if page.get_images(full=True):
            return False
        return not page.get_drawings()

    def _native_blocks(
        self,
        page: Any,
        context: ParseContext,
    ) -> list[EvidenceDraft]:
        drafts: list[EvidenceDraft] = []
        for raw in page.get_text("blocks", sort=True):
            if len(raw) < 7 or int(raw[6]) != 0:
                continue
            text = normalize_text(str(raw[4]))
            if not text:
                continue
            bbox = BBox(x0=float(raw[0]), y0=float(raw[1]), x1=float(raw[2]), y1=float(raw[3]))
            for chunk in chunk_text(
                text,
                context.settings.chunk_chars,
                context.settings.chunk_overlap,
            ):
                drafts.append(
                    EvidenceDraft(
                        text=chunk,
                        kind="text",
                        page=page.number + 1,
                        bbox=bbox,
                        confidence=1.0,
                        parser=self.name,
                        metadata={"coordinate_space": "pdf_points"},
                    )
                )
        return drafts

    def _native_tables(self, page: Any) -> list[EvidenceDraft]:
        pymupdf = load_pymupdf()
        drafts: list[EvidenceDraft] = []
        try:
            finder = page.find_tables()
        except Exception:
            return drafts
        for table_index, table in enumerate(finder.tables, start=1):
            rows = table.extract()
            text = "\n".join(
                "\t".join("" if cell is None else str(cell) for cell in row) for row in rows
            ).strip()
            if not text:
                continue
            rect = pymupdf.Rect(table.bbox)
            drafts.append(
                EvidenceDraft(
                    text=text,
                    kind="table",
                    page=page.number + 1,
                    bbox=BBox(x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1),
                    confidence=1.0,
                    parser=self.name,
                    metadata={
                        "coordinate_space": "pdf_points",
                        "table_index": table_index,
                    },
                )
            )
        return drafts

    def _ocr_page(
        self,
        page: Any,
        context: ParseContext,
        temporary_dir: Path,
    ) -> ParseResult:
        pymupdf = load_pymupdf()
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        image_path = temporary_dir / f"page-{page.number + 1:05d}.png"
        pixmap.save(image_path)
        result = context.ocr_engine.recognize(
            image_path,
            page=page.number + 1,
            languages=context.options.languages,
        )
        converted: list[EvidenceDraft] = []
        x_scale = page.rect.width / pixmap.width
        y_scale = page.rect.height / pixmap.height
        for block in result.blocks:
            if block.bbox is None or block.metadata.get("coordinate_space") != "image_pixels":
                converted.append(block)
                continue
            bbox = BBox(
                x0=page.rect.x0 + block.bbox.x0 * x_scale,
                y0=page.rect.y0 + block.bbox.y0 * y_scale,
                x1=page.rect.x0 + block.bbox.x1 * x_scale,
                y1=page.rect.y0 + block.bbox.y1 * y_scale,
            )
            metadata = {
                **block.metadata,
                "coordinate_space": "pdf_points",
                "ocr_source_coordinate_space": "image_pixels",
                "ocr_image_width": pixmap.width,
                "ocr_image_height": pixmap.height,
                "ocr_x_points_per_pixel": x_scale,
                "ocr_y_points_per_pixel": y_scale,
            }
            converted.append(block.model_copy(update={"bbox": bbox, "metadata": metadata}))
        return result.model_copy(update={"blocks": converted})

    def parse(self, context: ParseContext) -> ParseResult:
        pymupdf = load_pymupdf()
        blocks: list[EvidenceDraft] = []
        warnings: list[str] = []
        partial = False
        with (
            pymupdf.open(context.source_path) as document,
            tempfile.TemporaryDirectory(
                dir=context.work_dir,
                prefix="ocr-pages-",
            ) as temporary,
        ):
            page_count = document.page_count
            temporary_dir = Path(temporary)
            for page in document:
                native = self._native_blocks(page, context)
                native_chars = sum(len(block.text) for block in native)
                should_ocr = context.options.ocr_mode == "always" or (
                    context.options.ocr_mode == "auto" and native_chars < self.minimum_native_chars
                )
                if should_ocr and not native and self._is_structurally_blank(page):
                    continue
                if should_ocr and context.ocr_engine.available:
                    ocr_result = self._ocr_page(page, context, temporary_dir)
                    blocks.extend(ocr_result.blocks)
                    warnings.extend(ocr_result.warnings)
                    partial = partial or ocr_result.status == "partial"
                    if not ocr_result.blocks and native:
                        blocks.extend(native)
                else:
                    blocks.extend(native)
                    blocks.extend(self._native_tables(page))
                    if should_ocr and not context.ocr_engine.available:
                        partial = True
                        warnings.append(
                            f"Page {page.number + 1} has little native text and OCR is unavailable."
                        )
        return ParseResult(
            parser=self.name,
            parser_version=self.version,
            page_count=page_count,
            blocks=blocks,
            warnings=warnings,
            status="partial" if partial else "completed",
        )

    def diagnostic(self) -> str | None:
        try:
            load_pymupdf()
        except RuntimeError as exc:
            return str(exc)
        return None
