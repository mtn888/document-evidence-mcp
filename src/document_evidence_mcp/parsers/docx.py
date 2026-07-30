from __future__ import annotations

from importlib.metadata import version

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from document_evidence_mcp.chunking import chunk_text, normalize_text
from document_evidence_mcp.models import EvidenceDraft, ParseResult
from document_evidence_mcp.parsers.base import ParseContext


class DocxParser:
    name = "python-docx"
    version = version("python-docx")
    extensions = frozenset({".docx"})

    def parse(self, context: ParseContext) -> ParseResult:
        document = Document(context.source_path)
        blocks: list[EvidenceDraft] = []
        table_index = 0
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                text = normalize_text(item.text)
                if not text:
                    continue
                style = item.style.name if item.style is not None else None
                kind = "heading" if style and style.lower().startswith("heading") else "text"
                for chunk in chunk_text(
                    text,
                    context.settings.chunk_chars,
                    context.settings.chunk_overlap,
                ):
                    blocks.append(
                        EvidenceDraft(
                            text=chunk,
                            kind=kind,
                            section=style,
                            parser=self.name,
                            metadata={"coordinate_space": "none"},
                        )
                    )
            elif isinstance(item, Table):
                table_index += 1
                rows = [
                    "\t".join(normalize_text(cell.text) for cell in row.cells) for row in item.rows
                ]
                text = "\n".join(row for row in rows if row.strip())
                if text:
                    blocks.append(
                        EvidenceDraft(
                            text=text,
                            kind="table",
                            parser=self.name,
                            metadata={
                                "coordinate_space": "none",
                                "table_index": table_index,
                                "rows": len(item.rows),
                                "columns": len(item.columns),
                            },
                        )
                    )
        return ParseResult(
            parser=self.name,
            parser_version=self.version,
            page_count=None,
            blocks=blocks,
        )
