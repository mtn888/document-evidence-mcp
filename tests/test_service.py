from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from document_evidence_mcp.config import Settings
from document_evidence_mcp.service import DocumentEvidenceService
from document_evidence_mcp.store import EvidenceStore


def test_text_ingest_is_content_addressed_and_persistent(
    tmp_path: Path,
    settings: Settings,
    service: DocumentEvidenceService,
) -> None:
    first_path = tmp_path / "standard-a.md"
    second_path = tmp_path / "renamed-standard.md"
    content = (
        "# 第一章 安全要求\n\n"
        "安全阀的整定压力不得超过 12.5 MPa，并应记录检验日期。\n\n"  # noqa: RUF001
        "Die Prüfung ist jährlich zu dokumentieren."
    )
    first_path.write_text(content, encoding="utf-8")
    shutil.copyfile(first_path, second_path)

    first = service.ingest_document(first_path)
    cached = service.ingest_document(second_path)

    assert first.cached is False
    assert cached.cached is True
    assert cached.document_id == first.document_id
    assert first.evidence_count >= 1

    summary = service.get_document(first.document_id)
    assert set(summary.source_paths) == {str(first_path.resolve()), str(second_path.resolve())}
    assert Path(first.artifact_dir, "manifest.json").is_file()
    assert Path(first.artifact_dir, "blocks.jsonl").is_file()

    hits = service.search_evidence("安全阀", document_id=first.document_id)
    assert hits.hits
    assert hits.hits[0].document_id == first.document_id
    assert "安全阀" in hits.hits[0].text

    evidence = service.get_evidence([hits.hits[0].evidence_id])
    assert evidence.evidence[0].text == hits.hits[0].text

    restarted = DocumentEvidenceService(settings)
    assert restarted.get_document(first.document_id).source_sha256 == first.source_sha256
    assert restarted.search_evidence("jährlich").hits

    orphan = settings.version_root / f"doc_{first.source_sha256[:16]}_{first.profile_hash[:10]}_r2"
    orphan.mkdir(parents=True)
    (orphan / "stale.txt").write_text("interrupted ingest", encoding="utf-8")
    forced = restarted.ingest_document(first_path, force=True)
    assert forced.document_id != first.document_id
    assert forced.revision == first.revision + 1
    assert forced.source_sha256 == first.source_sha256
    assert not Path(forced.artifact_dir, "stale.txt").exists()
    assert len(restarted.list_documents()) == 2


def test_search_enforces_total_character_budget(
    tmp_path: Path,
    service: DocumentEvidenceService,
) -> None:
    source = tmp_path / "long.txt"
    source.write_text(
        "\n\n".join(
            f"pressure relief valve evidence section {index}: " + ("x" * 240) for index in range(8)
        ),
        encoding="utf-8",
    )
    document = service.ingest_document(source)

    result = service.search_evidence(
        "pressure relief",
        document_id=document.document_id,
        limit=8,
        max_chars=220,
    )

    assert result.hits
    assert result.used_chars <= 220
    assert result.truncated is True
    assert any(hit.truncated for hit in result.hits)


def test_allowed_roots_are_enforced(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    settings = Settings(
        store_root=tmp_path / "store",
        allowed_roots=(allowed.resolve(),),
        chunk_chars=320,
        chunk_overlap=40,
    )
    service = DocumentEvidenceService(settings)
    source = denied / "secret.txt"
    source.write_text("not allowed", encoding="utf-8")

    with pytest.raises(PermissionError, match="outside"):
        service.ingest_document(source)


def test_unsupported_extension_has_actionable_error(
    tmp_path: Path,
    service: DocumentEvidenceService,
) -> None:
    source = tmp_path / "legacy.wps"
    source.write_bytes(b"legacy")

    with pytest.raises(ValueError, match="unsupported document extension"):
        service.ingest_document(source)


def test_existing_unicode_fts_is_not_misreported_as_trigram(
    tmp_path: Path,
    settings: Settings,
) -> None:
    settings.ensure_directories()
    with closing(sqlite3.connect(settings.database_path)) as connection, connection:
        connection.execute(
            """
            CREATE VIRTUAL TABLE evidence_fts USING fts5(
                evidence_id UNINDEXED,
                document_id UNINDEXED,
                text,
                section,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )

    store = EvidenceStore(settings)

    assert store.fts5_available is True
    assert store.trigram_available is False
