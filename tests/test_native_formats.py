from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from document_evidence_mcp.service import DocumentEvidenceService


def test_docx_structural_ingest(
    tmp_path: Path,
    service: DocumentEvidenceService,
) -> None:
    path = tmp_path / "regulation.docx"
    document = Document()
    document.add_heading("Clause 4 — Sicherheitsventil", level=1)
    document.add_paragraph("Der Grenzwert beträgt 8 bar.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Parameter"
    table.cell(0, 1).text = "Wert"
    table.cell(1, 0).text = "Prüfdruck"
    table.cell(1, 1).text = "12 bar"
    document.save(path)

    ingested = service.ingest_document(path)
    heading = service.search_evidence("Sicherheitsventil", document_id=ingested.document_id)
    table_hit = service.search_evidence("Prüfdruck", document_id=ingested.document_id)

    assert heading.hits[0].kind == "heading"
    assert table_hit.hits[0].kind == "table"
    assert table_hit.hits[0].bbox is None


def test_xlsx_preserves_sheet_rows_and_formula_text(
    tmp_path: Path,
    service: DocumentEvidenceService,
) -> None:
    path = tmp_path / "limits.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Grenzwerte"
    sheet.append(["Parameter", "Wert"])
    sheet.append(["压力上限", 12.5])
    sheet.append(["Doppelt", "=B2*2"])
    workbook.save(path)

    ingested = service.ingest_document(path)
    result = service.search_evidence("压力上限", document_id=ingested.document_id)
    formula = service.search_evidence("B2*2", document_id=ingested.document_id)

    assert result.hits[0].section == "Grenzwerte"
    assert result.hits[0].metadata["row"] == 2
    assert formula.hits


def test_pptx_preserves_slide_and_shape_coordinates(
    tmp_path: Path,
    service: DocumentEvidenceService,
) -> None:
    path = tmp_path / "paper.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    shape.text = "Experimentelle Ergebnisse 2026"
    presentation.save(path)

    ingested = service.ingest_document(path)
    result = service.search_evidence("Experimentelle", document_id=ingested.document_id)

    assert result.hits[0].page == 1
    assert result.hits[0].bbox is not None
    assert result.hits[0].metadata["coordinate_space"] == "presentation_emu"
