from __future__ import annotations

from pathlib import Path

from document_evidence_mcp.parsers.base import DocumentParser
from document_evidence_mcp.parsers.doc import DocParser
from document_evidence_mcp.parsers.docx import DocxParser
from document_evidence_mcp.parsers.image import ImageParser
from document_evidence_mcp.parsers.pdf import PdfParser
from document_evidence_mcp.parsers.pptx import PptxParser
from document_evidence_mcp.parsers.text import TextParser
from document_evidence_mcp.parsers.xlsx import XlsxParser


class UnsupportedDocumentError(ValueError):
    pass


class ParserRouter:
    def __init__(self) -> None:
        parsers: list[DocumentParser] = [
            PdfParser(),
            DocParser(),
            DocxParser(),
            XlsxParser(),
            PptxParser(),
            ImageParser(),
            TextParser(),
        ]
        self._by_extension = {
            extension: parser for parser in parsers for extension in parser.extensions
        }

    @property
    def supported_extensions(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_extension))

    def parser_for(self, path: Path) -> DocumentParser:
        extension = path.suffix.lower()
        parser = self._by_extension.get(extension)
        if parser is None:
            supported = ", ".join(self.supported_extensions)
            raise UnsupportedDocumentError(
                f"unsupported document extension {extension or '<none>'}; supported: {supported}"
            )
        return parser

    def versions(self) -> dict[str, str]:
        unique = {parser.name: parser.version for parser in self._by_extension.values()}
        return dict(sorted(unique.items()))

    def diagnostics(self) -> list[str]:
        warnings: list[str] = []
        seen: set[str] = set()
        for parser in self._by_extension.values():
            if parser.name in seen:
                continue
            seen.add(parser.name)
            diagnostic = getattr(parser, "diagnostic", None)
            if diagnostic is not None and (message := diagnostic()):
                warnings.append(f"{parser.name}: {message}")
        return warnings
