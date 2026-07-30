from __future__ import annotations

import contextlib
import json

from document_evidence_mcp.chunking import chunk_text
from document_evidence_mcp.models import EvidenceDraft, ParseResult
from document_evidence_mcp.parsers.base import ParseContext


class TextParser:
    name = "text"
    version = "stdlib"
    extensions = frozenset({".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".xml", ".html"})

    def parse(self, context: ParseContext) -> ParseResult:
        raw = context.source_path.read_text(encoding="utf-8-sig", errors="replace")
        if context.source_path.suffix.lower() == ".json":
            with contextlib.suppress(json.JSONDecodeError):
                raw = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        blocks = [
            EvidenceDraft(text=value, parser=self.name)
            for value in chunk_text(
                raw,
                context.settings.chunk_chars,
                context.settings.chunk_overlap,
            )
        ]
        return ParseResult(
            parser=self.name,
            parser_version=self.version,
            page_count=None,
            blocks=blocks,
        )
