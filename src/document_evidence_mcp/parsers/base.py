from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from document_evidence_mcp.config import Settings
from document_evidence_mcp.models import IngestOptions, ParseResult


class OcrEngine(Protocol):
    name: str
    version: str

    @property
    def available(self) -> bool: ...

    def recognize(
        self,
        image_path: Path,
        *,
        page: int,
        languages: list[str],
    ) -> ParseResult: ...


@dataclass(frozen=True, slots=True)
class ParseContext:
    source_path: Path
    work_dir: Path
    options: IngestOptions
    settings: Settings
    ocr_engine: OcrEngine


class DocumentParser(Protocol):
    name: str
    version: str
    extensions: frozenset[str]

    def parse(self, context: ParseContext) -> ParseResult: ...
