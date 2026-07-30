from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from document_evidence_mcp.config import Settings
from document_evidence_mcp.models import BBox, DocumentSummary, EvidenceDraft
from document_evidence_mcp.utils import utc_now

SCHEMA_VERSION = 1
_WORD = re.compile(r"[\w\u3400-\u9fff]+", re.UNICODE)
_CJK = re.compile(r"[\u3400-\u9fff]")


class IngestionLockTimeout(TimeoutError):
    pass


class EvidenceStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self.fts5_available = False
        self.trigram_available = False
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.settings.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    source_size INTEGER NOT NULL,
                    source_suffix TEXT NOT NULL,
                    object_path TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    parser TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('completed', 'partial')),
                    page_count INTEGER,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    artifact_dir TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    UNIQUE (source_sha256, profile_hash, revision)
                );

                CREATE INDEX IF NOT EXISTS idx_documents_cache
                    ON documents(source_sha256, profile_hash, revision DESC);
                CREATE INDEX IF NOT EXISTS idx_documents_indexed_at
                    ON documents(indexed_at DESC);

                CREATE TABLE IF NOT EXISTS document_sources (
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    source_path TEXT NOT NULL,
                    seen_at TEXT NOT NULL,
                    PRIMARY KEY (document_id, source_path)
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    page INTEGER,
                    bbox_json TEXT,
                    confidence REAL,
                    section TEXT,
                    parser TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE (document_id, ordinal)
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_document
                    ON evidence(document_id, ordinal);

                CREATE TABLE IF NOT EXISTS ingestion_locks (
                    identity TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
                );
                """
            )
            fts_schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'evidence_fts'"
            ).fetchone()
            if fts_schema is None:
                try:
                    connection.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                            evidence_id UNINDEXED,
                            document_id UNINDEXED,
                            text,
                            section,
                            tokenize='trigram'
                        )
                        """
                    )
                except sqlite3.OperationalError:
                    with suppress(sqlite3.OperationalError):
                        connection.execute(
                            """
                            CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                                evidence_id UNINDEXED,
                                document_id UNINDEXED,
                                text,
                                section,
                                tokenize='unicode61 remove_diacritics 2'
                            )
                            """
                        )
                fts_schema = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'evidence_fts'"
                ).fetchone()
            self.fts5_available = fts_schema is not None
            self.trigram_available = bool(
                fts_schema is not None and "trigram" in fts_schema["sql"].lower()
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def acquire_ingestion_lock(
        self,
        identity: str,
        *,
        wait_seconds: float = 30.0,
        stale_after: timedelta = timedelta(hours=2),
    ) -> str:
        owner = uuid.uuid4().hex
        deadline = time.monotonic() + wait_seconds
        while True:
            now = datetime.now(UTC)
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO ingestion_locks(identity, owner, acquired_at)
                        VALUES (?, ?, ?)
                        """,
                        (identity, owner, now.isoformat()),
                    )
                return owner
            except sqlite3.IntegrityError:
                with self._connect() as connection:
                    row = connection.execute(
                        "SELECT owner, acquired_at FROM ingestion_locks WHERE identity = ?",
                        (identity,),
                    ).fetchone()
                    if row is not None:
                        acquired_at = datetime.fromisoformat(row["acquired_at"])
                        if now - acquired_at > stale_after:
                            connection.execute(
                                "DELETE FROM ingestion_locks WHERE identity = ? AND owner = ?",
                                (identity, row["owner"]),
                            )
                            continue
                if time.monotonic() >= deadline:
                    raise IngestionLockTimeout(
                        f"another process is still ingesting {identity}"
                    ) from None
                time.sleep(0.1)

    def release_ingestion_lock(self, identity: str, owner: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM ingestion_locks WHERE identity = ? AND owner = ?",
                (identity, owner),
            )

    def find_cached(self, source_sha256: str, profile_hash: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT * FROM documents
                WHERE source_sha256 = ? AND profile_hash = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (source_sha256, profile_hash),
            ).fetchone()

    def next_revision(self, source_sha256: str, profile_hash: str) -> int:
        with self._connect() as connection:
            value = connection.execute(
                """
                SELECT COALESCE(MAX(revision), 0) + 1
                FROM documents
                WHERE source_sha256 = ? AND profile_hash = ?
                """,
                (source_sha256, profile_hash),
            ).fetchone()[0]
        return int(value)

    def insert_document(
        self,
        *,
        document: dict[str, Any],
        source_path: Path,
        blocks: Sequence[EvidenceDraft],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents(
                    document_id, source_name, source_sha256, source_size, source_suffix,
                    object_path, profile_hash, revision, parser, parser_version, status,
                    page_count, evidence_count, warnings_json, artifact_dir, indexed_at
                ) VALUES (
                    :document_id, :source_name, :source_sha256, :source_size, :source_suffix,
                    :object_path, :profile_hash, :revision, :parser, :parser_version, :status,
                    :page_count, :evidence_count, :warnings_json, :artifact_dir, :indexed_at
                )
                """,
                document,
            )
            connection.execute(
                """
                INSERT INTO document_sources(document_id, source_path, seen_at)
                VALUES (?, ?, ?)
                """,
                (document["document_id"], str(source_path), utc_now()),
            )
            for ordinal, block in enumerate(blocks, start=1):
                evidence_id = f"{document['document_id']}:e{ordinal:06d}"
                bbox_json = (
                    json.dumps(block.bbox.model_dump(mode="json"), separators=(",", ":"))
                    if block.bbox is not None
                    else None
                )
                metadata_json = json.dumps(
                    block.metadata,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    """
                    INSERT INTO evidence(
                        evidence_id, document_id, ordinal, text, kind, page, bbox_json,
                        confidence, section, parser, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        document["document_id"],
                        ordinal,
                        block.text,
                        block.kind,
                        block.page,
                        bbox_json,
                        block.confidence,
                        block.section,
                        block.parser,
                        metadata_json,
                    ),
                )
                if self.fts5_available:
                    connection.execute(
                        """
                        INSERT INTO evidence_fts(evidence_id, document_id, text, section)
                        VALUES (?, ?, ?, ?)
                        """,
                        (evidence_id, document["document_id"], block.text, block.section or ""),
                    )

    def record_source(self, document_id: str, source_path: Path) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO document_sources(document_id, source_path, seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(document_id, source_path)
                DO UPDATE SET seen_at = excluded.seen_at
                """,
                (document_id, str(source_path), utc_now()),
            )

    def get_document_row(self, document_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown document_id: {document_id}")
        return row

    def _sources_for(self, connection: sqlite3.Connection, document_id: str) -> list[str]:
        rows = connection.execute(
            """
            SELECT source_path FROM document_sources
            WHERE document_id = ?
            ORDER BY seen_at DESC
            """,
            (document_id,),
        ).fetchall()
        return [row["source_path"] for row in rows]

    def document_summary(self, document_id: str) -> DocumentSummary:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown document_id: {document_id}")
            sources = self._sources_for(connection, document_id)
        return self._summary_from_row(row, sources)

    def list_documents(self, limit: int) -> list[DocumentSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM documents
                ORDER BY indexed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                self._summary_from_row(row, self._sources_for(connection, row["document_id"]))
                for row in rows
            ]

    @staticmethod
    def _summary_from_row(row: sqlite3.Row, sources: list[str]) -> DocumentSummary:
        return DocumentSummary(
            document_id=row["document_id"],
            source_name=row["source_name"],
            source_sha256=row["source_sha256"],
            profile_hash=row["profile_hash"],
            revision=row["revision"],
            parser=row["parser"],
            status=row["status"],
            page_count=row["page_count"],
            evidence_count=row["evidence_count"],
            indexed_at=row["indexed_at"],
            source_paths=sources,
        )

    def _fts_expression(self, query: str) -> str | None:
        terms: list[str] = []
        for token in _WORD.findall(query):
            token = token.strip("_")
            if not token:
                continue
            if self.trigram_available and _CJK.search(token) and len(token) > 6:
                terms.extend(token[index : index + 3] for index in range(len(token) - 2))
            elif not self.trigram_available or len(token) >= 3:
                terms.append(token)
        deduplicated = list(dict.fromkeys(terms))[:24]
        if not deduplicated:
            return None
        return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in deduplicated)

    def search_rows(
        self,
        query: str,
        *,
        document_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("query must not be empty")
        expression = self._fts_expression(query)
        rows: list[sqlite3.Row] = []
        with self._connect() as connection:
            if self.fts5_available and expression:
                where_document = "AND e.document_id = ?" if document_id else ""
                parameters: list[Any] = [expression]
                if document_id:
                    parameters.append(document_id)
                parameters.append(limit)
                rows = connection.execute(
                    f"""
                    SELECT e.*, bm25(evidence_fts) AS rank
                    FROM evidence_fts
                    JOIN evidence e USING(evidence_id)
                    WHERE evidence_fts MATCH ?
                    {where_document}
                    ORDER BY rank ASC, e.ordinal ASC
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
            if not rows:
                where_document = "AND document_id = ?" if document_id else ""
                parameters = [f"%{query.strip()}%"]
                if document_id:
                    parameters.append(document_id)
                parameters.append(limit)
                rows = connection.execute(
                    f"""
                    SELECT *, 0.0 AS rank
                    FROM evidence
                    WHERE text LIKE ?
                    {where_document}
                    ORDER BY document_id, ordinal
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
        return [self._evidence_dict(row, rank=float(row["rank"])) for row in rows]

    def get_evidence_rows(self, evidence_ids: Sequence[str]) -> list[dict[str, Any]]:
        if not evidence_ids:
            return []
        placeholders = ",".join("?" for _ in evidence_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM evidence WHERE evidence_id IN ({placeholders})",
                list(evidence_ids),
            ).fetchall()
        by_id = {row["evidence_id"]: self._evidence_dict(row) for row in rows}
        missing = [value for value in evidence_ids if value not in by_id]
        if missing:
            raise KeyError(f"unknown evidence_id(s): {', '.join(missing)}")
        return [by_id[value] for value in evidence_ids]

    @staticmethod
    def _evidence_dict(row: sqlite3.Row, rank: float | None = None) -> dict[str, Any]:
        value: dict[str, Any] = {
            "evidence_id": row["evidence_id"],
            "document_id": row["document_id"],
            "ordinal": row["ordinal"],
            "text": row["text"],
            "kind": row["kind"],
            "page": row["page"],
            "bbox": BBox.model_validate_json(row["bbox_json"]) if row["bbox_json"] else None,
            "confidence": row["confidence"],
            "section": row["section"],
            "parser": row["parser"],
            "metadata": json.loads(row["metadata_json"]),
            "truncated": False,
        }
        if rank is not None:
            value["rank"] = rank
        return value
