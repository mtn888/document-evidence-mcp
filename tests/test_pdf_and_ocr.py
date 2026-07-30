from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from document_evidence_mcp.models import BBox, EvidenceDraft, ParseResult
from document_evidence_mcp.parsers.ocr import PaddleOcrEngine
from document_evidence_mcp.service import DocumentEvidenceService


class FakeOcrEngine:
    name = "fake-ocr"
    version = "test-1"

    def __init__(self) -> None:
        self.calls: list[tuple[int, list[str]]] = []

    @property
    def available(self) -> bool:
        return True

    def recognize(
        self,
        image_path: Path,
        *,
        page: int,
        languages: list[str],
    ) -> ParseResult:
        assert image_path.is_file()
        self.calls.append((page, languages))
        return ParseResult(
            parser=self.name,
            parser_version=self.version,
            page_count=1,
            blocks=[
                EvidenceDraft(
                    text="扫描证据 OCR Ergebnis",
                    kind="ocr_text",
                    page=page,
                    bbox=BBox(x0=10, y0=20, x1=180, y1=60),
                    confidence=0.97,
                    parser=self.name,
                    metadata={"coordinate_space": "image_pixels"},
                )
            ],
        )


def _make_pdf(path: Path, text: str | None) -> None:
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    if text:
        page.insert_text((30, 60), text)
    document.save(path)
    document.close()


def _make_scanned_pdf(path: Path) -> None:
    image_document = pymupdf.open()
    image_page = image_document.new_page(width=300, height=200)
    image_page.insert_text((30, 60), "Raster scan")
    image = image_page.get_pixmap(alpha=False).tobytes("png")
    image_document.close()

    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_image(page.rect, stream=image)
    document.save(path)
    document.close()


def test_native_pdf_evidence_and_crop(
    tmp_path: Path,
    service: DocumentEvidenceService,
) -> None:
    path = tmp_path / "native.pdf"
    _make_pdf(path, "Safety valve requirement 12.5 MPa")

    ingested = service.ingest_document(path, ocr_mode="never")
    result = service.search_evidence("Safety valve", document_id=ingested.document_id)

    assert ingested.status == "completed"
    assert ingested.page_count == 1
    assert result.hits[0].page == 1
    assert result.hits[0].bbox is not None
    assert result.hits[0].metadata["coordinate_space"] == "pdf_points"

    crop = service.render_crop(
        ingested.document_id,
        page=1,
        bbox=BBox(x0=20, y0=30, x1=260, y1=100),
        dpi=144,
    )
    cached = service.render_crop(
        ingested.document_id,
        page=1,
        bbox=BBox(x0=20, y0=30, x1=260, y1=100),
        dpi=144,
    )

    assert Path(crop.artifact_path).is_file()
    assert crop.width > 0 and crop.height > 0
    assert cached.artifact_path == crop.artifact_path
    assert cached.cached is True


def test_scanned_pdf_routes_only_low_text_page_to_ocr(
    tmp_path: Path,
    settings,
) -> None:
    path = tmp_path / "scan.pdf"
    _make_scanned_pdf(path)
    fake = FakeOcrEngine()
    service = DocumentEvidenceService(settings, ocr_engine=fake)

    ingested = service.ingest_document(path, languages=["zh", "de"], ocr_mode="auto")
    result = service.search_evidence("扫描证据", document_id=ingested.document_id)

    assert fake.calls == [(1, ["zh", "de"])]
    assert ingested.status == "completed"
    assert result.hits[0].confidence == 0.97
    assert result.hits[0].parser == "fake-ocr"
    assert result.hits[0].bbox == BBox(x0=5, y0=10, x1=90, y1=30)
    assert result.hits[0].metadata["coordinate_space"] == "pdf_points"
    assert result.hits[0].metadata["ocr_source_coordinate_space"] == "image_pixels"
    assert result.hits[0].metadata["ocr_image_width"] == 600
    assert result.hits[0].metadata["ocr_image_height"] == 400


def test_structurally_blank_pdf_page_does_not_trigger_ocr(
    tmp_path: Path,
    settings,
) -> None:
    path = tmp_path / "blank.pdf"
    _make_pdf(path, None)
    fake = FakeOcrEngine()
    service = DocumentEvidenceService(settings, ocr_engine=fake)

    ingested = service.ingest_document(path, ocr_mode="auto")

    assert fake.calls == []
    assert ingested.status == "completed"
    assert ingested.evidence_count == 0
    assert ingested.warnings == []


def test_paddle_adapter_accepts_numpy_like_table_boxes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    class NumpyLikeBoxes:
        def __bool__(self) -> bool:
            raise ValueError("ambiguous truth value")

        def __len__(self) -> int:
            return 2

        def __iter__(self):
            return iter(([10, 20, 50, 60], [55, 20, 100, 60]))

    class FakePipeline:
        def predict(self, image_path: str):
            assert Path(image_path).is_file()
            return [
                {
                    "overall_ocr_res": {
                        "rec_texts": [],
                        "rec_scores": [],
                        "rec_boxes": [],
                    },
                    "table_res_list": [
                        {
                            "pred_html": "<table><tr><td>A</td><td>B</td></tr></table>",
                            "cell_box_list": NumpyLikeBoxes(),
                        }
                    ],
                }
            ]

    image_path = tmp_path / "table.png"
    image_path.write_bytes(b"fake")
    engine = PaddleOcrEngine()
    monkeypatch.setattr(engine, "_pipeline", lambda _language: FakePipeline())

    result = engine.recognize(image_path, page=3, languages=["zh"])

    assert result.status == "completed"
    assert result.blocks[0].kind == "table"
    assert result.blocks[0].text == "A B"
    assert result.blocks[0].bbox == BBox(x0=10, y0=20, x1=100, y1=60)
