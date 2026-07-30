from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceKind = Literal[
    "text",
    "heading",
    "table",
    "table_row",
    "note",
    "ocr_text",
]
OcrMode = Literal["auto", "never", "always"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BBox(StrictModel):
    """Rectangle in the coordinate space named by the evidence metadata."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def validate_order(self) -> BBox:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("bbox must have positive width and height")
        return self


class EvidenceDraft(StrictModel):
    text: str
    kind: EvidenceKind = "text"
    page: int | None = Field(default=None, ge=1)
    bbox: BBox | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    section: str | None = None
    parser: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParseResult(StrictModel):
    parser: str
    parser_version: str
    page_count: int | None = Field(default=None, ge=0)
    blocks: list[EvidenceDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["completed", "partial"] = "completed"


class IngestOptions(StrictModel):
    languages: list[str] = Field(default_factory=lambda: ["zh", "en", "de"])
    ocr_mode: OcrMode = "auto"
    force: bool = False


class IngestResult(StrictModel):
    document_id: str
    cached: bool
    status: Literal["completed", "partial"]
    source_sha256: str
    profile_hash: str
    revision: int = Field(ge=1)
    parser: str
    page_count: int | None = None
    evidence_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    artifact_dir: str


class DocumentSummary(StrictModel):
    document_id: str
    source_name: str
    source_sha256: str
    profile_hash: str
    revision: int
    parser: str
    status: Literal["completed", "partial"]
    page_count: int | None
    evidence_count: int
    indexed_at: str
    source_paths: list[str] = Field(default_factory=list)


class EvidenceRecord(StrictModel):
    evidence_id: str
    document_id: str
    ordinal: int
    text: str
    kind: EvidenceKind
    page: int | None
    bbox: BBox | None
    confidence: float | None
    section: str | None
    parser: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False


class SearchHit(EvidenceRecord):
    rank: float


class SearchResult(StrictModel):
    query: str
    hits: list[SearchHit]
    used_chars: int
    max_chars: int
    truncated: bool


class EvidenceResult(StrictModel):
    evidence: list[EvidenceRecord]
    used_chars: int
    max_chars: int
    truncated: bool


class CropResult(StrictModel):
    document_id: str
    page: int
    bbox: BBox
    dpi: int
    artifact_path: str
    sha256: str
    width: int
    height: int
    cached: bool


class DoctorResult(StrictModel):
    store_root: str
    database_path: str
    sqlite_version: str
    fts5_available: bool
    trigram_available: bool
    parsers: dict[str, str]
    ocr_provider: str
    ocr_available: bool
    warnings: list[str] = Field(default_factory=list)
