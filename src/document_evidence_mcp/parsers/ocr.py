from __future__ import annotations

import html
import importlib.util
import os
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from document_evidence_mcp.chunking import normalize_text
from document_evidence_mcp.models import BBox, EvidenceDraft, ParseResult


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unavailable"


class NullOcrEngine:
    name = "none"
    version = "none"

    @property
    def available(self) -> bool:
        return False

    def recognize(
        self,
        image_path: Path,
        *,
        page: int,
        languages: list[str],
    ) -> ParseResult:
        del image_path, page, languages
        return ParseResult(
            parser=self.name,
            parser_version=self.version,
            status="partial",
            warnings=["OCR was required but DOCUMENT_EVIDENCE_OCR_PROVIDER is none."],
        )


def _select_paddle_language(languages: list[str]) -> str:
    normalized = {item.lower().replace("_", "-") for item in languages}
    if normalized & {"zh", "zh-cn", "zh-hans", "ch", "chinese"}:
        return "ch"
    if normalized & {"de", "de-de", "german"}:
        return "german"
    return "en"


def _box_from_value(value: Any) -> BBox | None:
    if value is None:
        return None
    try:
        points = value.tolist() if hasattr(value, "tolist") else value
        if len(points) == 4 and all(not isinstance(item, (list, tuple)) for item in points):
            x0, y0, x1, y1 = (float(item) for item in points)
        else:
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if x1 <= x0 or y1 <= y0:
            return None
        return BBox(x0=x0, y0=y0, x1=x1, y1=y1)
    except (TypeError, ValueError, IndexError):
        return None


def _has_items(value: Any) -> bool:
    if value is None:
        return False
    try:
        return len(value) > 0
    except TypeError:
        return False


_HTML_TAG = re.compile(r"<[^>]+>")


def _html_to_searchable_text(value: str) -> str:
    value = re.sub(r"</(?:td|th)>", "\t", value, flags=re.IGNORECASE)
    value = re.sub(r"</tr>", "\n", value, flags=re.IGNORECASE)
    return normalize_text(html.unescape(_HTML_TAG.sub("", value)))


class PaddleOcrEngine:
    """Lazy PP-StructureV3 adapter; importing the core package never loads OCR models."""

    name = "paddleocr-ppstructurev3"

    def __init__(self) -> None:
        self.version = _package_version("paddleocr")
        self._pipelines: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("paddleocr") is not None

    def _pipeline(self, language: str) -> Any:
        if language not in self._pipelines:
            if not self.available:
                raise RuntimeError(
                    "PaddleOCR is not installed. Install document-evidence-mcp[ocr] "
                    "and the appropriate Paddle inference runtime."
                )
            from paddleocr import PPStructureV3

            options: dict[str, Any] = {
                "lang": language,
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "use_seal_recognition": False,
                "use_table_recognition": True,
                "use_formula_recognition": False,
                "use_chart_recognition": False,
                "use_region_detection": False,
            }
            device = os.environ.get("DOCUMENT_EVIDENCE_OCR_DEVICE", "").strip()
            if device:
                options["device"] = device
            self._pipelines[language] = PPStructureV3(
                **options,
            )
        return self._pipelines[language]

    def recognize(
        self,
        image_path: Path,
        *,
        page: int,
        languages: list[str],
    ) -> ParseResult:
        language = _select_paddle_language(languages)
        pipeline = self._pipeline(language)
        predictions = list(pipeline.predict(str(image_path)))
        blocks: list[EvidenceDraft] = []
        warnings: list[str] = []
        if not predictions:
            return ParseResult(
                parser=self.name,
                parser_version=self.version,
                page_count=1,
                status="partial",
                warnings=[f"PaddleOCR returned no result for page {page}."],
            )

        result = predictions[0]
        ocr = result.get("overall_ocr_res", result)
        texts = list(ocr.get("rec_texts", []))
        scores = list(ocr.get("rec_scores", []))
        boxes = list(ocr.get("rec_boxes", ocr.get("dt_polys", [])))
        for index, raw_text in enumerate(texts):
            text = normalize_text(str(raw_text))
            if not text:
                continue
            score = float(scores[index]) if index < len(scores) else None
            box = _box_from_value(boxes[index]) if index < len(boxes) else None
            blocks.append(
                EvidenceDraft(
                    text=text,
                    kind="ocr_text",
                    page=page,
                    bbox=box,
                    confidence=score,
                    parser=self.name,
                    metadata={
                        "coordinate_space": "image_pixels",
                        "language_model": language,
                    },
                )
            )

        for index, table in enumerate(result.get("table_res_list", []), start=1):
            table_text = _html_to_searchable_text(str(table.get("pred_html", "")))
            if not table_text:
                continue
            cell_boxes = table.get("cell_box_list", [])
            table_box = None
            if _has_items(cell_boxes):
                valid_boxes = [_box_from_value(value) for value in cell_boxes]
                valid_boxes = [value for value in valid_boxes if value is not None]
                if valid_boxes:
                    table_box = BBox(
                        x0=min(value.x0 for value in valid_boxes),
                        y0=min(value.y0 for value in valid_boxes),
                        x1=max(value.x1 for value in valid_boxes),
                        y1=max(value.y1 for value in valid_boxes),
                    )
            blocks.append(
                EvidenceDraft(
                    text=table_text,
                    kind="table",
                    page=page,
                    bbox=table_box,
                    parser=self.name,
                    metadata={
                        "coordinate_space": "image_pixels",
                        "language_model": language,
                        "table_index": index,
                    },
                )
            )

        if not blocks:
            warnings.append(f"PaddleOCR found no text or table evidence on page {page}.")
        return ParseResult(
            parser=self.name,
            parser_version=self.version,
            page_count=1,
            blocks=blocks,
            warnings=warnings,
            status="completed" if blocks else "partial",
        )


def build_ocr_engine(provider: str) -> NullOcrEngine | PaddleOcrEngine:
    if provider == "paddleocr":
        return PaddleOcrEngine()
    return NullOcrEngine()
