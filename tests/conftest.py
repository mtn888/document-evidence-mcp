from __future__ import annotations

from pathlib import Path

import pytest

from document_evidence_mcp.config import Settings
from document_evidence_mcp.service import DocumentEvidenceService


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        store_root=tmp_path / "store",
        allowed_roots=(tmp_path.resolve(),),
        max_file_bytes=10 * 1024 * 1024,
        chunk_chars=320,
        chunk_overlap=40,
        doc_conversion_timeout_seconds=60,
        max_search_chars=1_200,
        max_search_hits=10,
        ocr_provider="none",
    )


@pytest.fixture
def service(settings: Settings) -> DocumentEvidenceService:
    return DocumentEvidenceService(settings)
