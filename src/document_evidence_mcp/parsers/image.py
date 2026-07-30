from __future__ import annotations

from document_evidence_mcp.models import ParseResult
from document_evidence_mcp.parsers.base import ParseContext


class ImageParser:
    name = "image-ocr"
    version = "1"
    extensions = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"})

    def parse(self, context: ParseContext) -> ParseResult:
        if context.options.ocr_mode == "never":
            return ParseResult(
                parser=self.name,
                parser_version=self.version,
                page_count=1,
                status="partial",
                warnings=["Image ingestion requires OCR but ocr_mode is never."],
            )
        return context.ocr_engine.recognize(
            context.source_path,
            page=1,
            languages=context.options.languages,
        )
