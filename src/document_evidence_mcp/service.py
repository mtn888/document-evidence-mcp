from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from document_evidence_mcp import __version__
from document_evidence_mcp.config import Settings
from document_evidence_mcp.models import (
    BBox,
    CropResult,
    DoctorResult,
    DocumentSummary,
    EvidenceRecord,
    EvidenceResult,
    IngestOptions,
    IngestResult,
    SearchHit,
    SearchResult,
)
from document_evidence_mcp.parsers.base import OcrEngine, ParseContext
from document_evidence_mcp.parsers.ocr import build_ocr_engine
from document_evidence_mcp.parsers.pdf import load_pymupdf
from document_evidence_mcp.parsers.router import ParserRouter
from document_evidence_mcp.store import EvidenceStore
from document_evidence_mcp.utils import (
    canonical_json_hash,
    clamp,
    sha256_file,
    sha256_text,
    utc_now,
    write_json_atomic,
)


class DocumentEvidenceService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        router: ParserRouter | None = None,
        ocr_engine: OcrEngine | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.settings.validate()
        self.settings.ensure_directories()
        self.router = router or ParserRouter()
        self.ocr_engine = ocr_engine or build_ocr_engine(self.settings.ocr_provider)
        self.store = EvidenceStore(self.settings)

    def _profile(self, parser: Any, options: IngestOptions) -> tuple[dict[str, Any], str]:
        profile = {
            "schema_version": 1,
            "document_evidence_version": __version__,
            "parser": {"name": parser.name, "version": parser.version},
            "chunk_chars": self.settings.chunk_chars,
            "chunk_overlap": self.settings.chunk_overlap,
            "ocr": {
                "provider": self.ocr_engine.name,
                "version": self.ocr_engine.version,
                "mode": options.ocr_mode,
                "languages": sorted({item.lower() for item in options.languages}),
            },
        }
        return profile, canonical_json_hash(profile)

    def _ensure_object(self, source: Path, source_sha256: str) -> Path:
        object_dir = self.settings.object_root / source_sha256[:2] / source_sha256
        object_path = object_dir / f"source{source.suffix.lower()}"
        if object_path.exists():
            if sha256_file(object_path) != source_sha256:
                raise RuntimeError(f"content-addressed object hash mismatch: {object_path}")
            return object_path
        object_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=object_dir,
            prefix=".source.",
            suffix=".tmp",
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            if sha256_file(temporary) != source_sha256:
                raise RuntimeError("source changed while it was being copied")
            os.replace(temporary, object_path)
        finally:
            temporary.unlink(missing_ok=True)
        return object_path

    @staticmethod
    def _ingest_result_from_row(row: sqlite3.Row, *, cached: bool) -> IngestResult:
        return IngestResult(
            document_id=row["document_id"],
            cached=cached,
            status=row["status"],
            source_sha256=row["source_sha256"],
            profile_hash=row["profile_hash"],
            revision=row["revision"],
            parser=row["parser"],
            page_count=row["page_count"],
            evidence_count=row["evidence_count"],
            warnings=json.loads(row["warnings_json"]),
            artifact_dir=row["artifact_dir"],
        )

    def ingest_document(
        self,
        path: str | Path,
        *,
        languages: list[str] | None = None,
        ocr_mode: str = "auto",
        force: bool = False,
    ) -> IngestResult:
        source = self.settings.resolve_input_file(path)
        options = IngestOptions(
            languages=languages or ["zh", "en", "de"],
            ocr_mode=ocr_mode,
            force=force,
        )
        parser = self.router.parser_for(source)
        source_sha256 = sha256_file(source)
        profile, profile_hash = self._profile(parser, options)
        shared_cache_key = getattr(parser, "shared_cache_key", None)
        lock_scope = f"shared:{shared_cache_key}" if shared_cache_key else f"profile:{profile_hash}"
        identity = f"{source_sha256}:{lock_scope}"
        owner = self.store.acquire_ingestion_lock(identity)
        try:
            cached = self.store.find_cached(source_sha256, profile_hash)
            if cached is not None and not force:
                self.store.record_source(cached["document_id"], source)
                return self._ingest_result_from_row(cached, cached=True)

            revision = self.store.next_revision(source_sha256, profile_hash)
            document_id = f"doc_{source_sha256[:16]}_{profile_hash[:10]}_r{revision}"
            object_path = self._ensure_object(source, source_sha256)
            source_size = object_path.stat().st_size
            final_dir = self.settings.version_root / document_id
            work_dir = self.settings.version_root / f".{document_id}.{os.getpid()}.work"
            if final_dir.exists():
                # The SQLite row is absent here, so this is an artifact left by a process
                # that stopped after the atomic rename but before committing the index.
                shutil.rmtree(final_dir)
            if work_dir.exists():
                shutil.rmtree(work_dir)
            work_dir.mkdir(parents=True)
            try:
                parse_result = parser.parse(
                    ParseContext(
                        source_path=object_path,
                        work_dir=work_dir,
                        options=options,
                        settings=self.settings,
                        ocr_engine=self.ocr_engine,
                    )
                )
                blocks_path = work_dir / "blocks.jsonl"
                with blocks_path.open("w", encoding="utf-8", newline="\n") as handle:
                    for ordinal, block in enumerate(parse_result.blocks, start=1):
                        record = {
                            "evidence_id": f"{document_id}:e{ordinal:06d}",
                            **block.model_dump(mode="json"),
                        }
                        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                        handle.write("\n")

                manifest = {
                    "schema_version": 1,
                    "document_id": document_id,
                    "source_name": source.name,
                    "source_path_at_ingest": str(source),
                    "source_sha256": source_sha256,
                    "source_size": source_size,
                    "object_path": str(object_path),
                    "profile": profile,
                    "profile_hash": profile_hash,
                    "revision": revision,
                    "parser": parse_result.parser,
                    "parser_version": parse_result.parser_version,
                    "status": parse_result.status,
                    "page_count": parse_result.page_count,
                    "evidence_count": len(parse_result.blocks),
                    "warnings": parse_result.warnings,
                    "indexed_at": utc_now(),
                }
                write_json_atomic(work_dir / "manifest.json", manifest)
                if final_dir.exists():
                    raise RuntimeError(f"version artifact already exists: {final_dir}")
                work_dir.rename(final_dir)

                document_row = {
                    "document_id": document_id,
                    "source_name": source.name,
                    "source_sha256": source_sha256,
                    "source_size": source_size,
                    "source_suffix": source.suffix.lower(),
                    "object_path": str(object_path),
                    "profile_hash": profile_hash,
                    "revision": revision,
                    "parser": parse_result.parser,
                    "parser_version": parse_result.parser_version,
                    "status": parse_result.status,
                    "page_count": parse_result.page_count,
                    "evidence_count": len(parse_result.blocks),
                    "warnings_json": json.dumps(
                        parse_result.warnings,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "artifact_dir": str(final_dir),
                    "indexed_at": manifest["indexed_at"],
                }
                try:
                    self.store.insert_document(
                        document=document_row,
                        source_path=source,
                        blocks=parse_result.blocks,
                    )
                except Exception:
                    shutil.rmtree(final_dir)
                    raise
                row = self.store.get_document_row(document_id)
                return self._ingest_result_from_row(row, cached=False)
            except Exception:
                if work_dir.exists():
                    shutil.rmtree(work_dir)
                raise
        finally:
            self.store.release_ingestion_lock(identity, owner)

    def list_documents(self, limit: int = 20) -> list[DocumentSummary]:
        return self.store.list_documents(clamp(limit, 1, 100))

    def get_document(self, document_id: str) -> DocumentSummary:
        return self.store.document_summary(document_id)

    def search_evidence(
        self,
        query: str,
        *,
        document_id: str | None = None,
        limit: int = 4,
        max_chars: int = 6_000,
    ) -> SearchResult:
        actual_limit = clamp(limit, 1, self.settings.max_search_hits)
        actual_max_chars = clamp(max_chars, 200, self.settings.max_search_chars)
        rows = self.store.search_rows(
            query,
            document_id=document_id,
            limit=actual_limit,
        )
        hits: list[SearchHit] = []
        used_chars = 0
        truncated = False
        for row in rows:
            remaining = actual_max_chars - used_chars
            if remaining <= 0:
                truncated = True
                break
            text = row["text"]
            if len(text) > remaining:
                row["text"] = text[:remaining]
                row["truncated"] = True
                truncated = True
            used_chars += len(row["text"])
            hits.append(SearchHit.model_validate(row))
        return SearchResult(
            query=query,
            hits=hits,
            used_chars=used_chars,
            max_chars=actual_max_chars,
            truncated=truncated or len(hits) < len(rows),
        )

    def get_evidence(
        self,
        evidence_ids: list[str],
        *,
        max_chars: int = 8_000,
    ) -> EvidenceResult:
        if len(evidence_ids) > self.settings.max_search_hits:
            raise ValueError(
                f"at most {self.settings.max_search_hits} evidence IDs may be requested"
            )
        actual_max_chars = clamp(max_chars, 200, self.settings.max_search_chars)
        rows = self.store.get_evidence_rows(evidence_ids)
        evidence: list[EvidenceRecord] = []
        used_chars = 0
        truncated = False
        for row in rows:
            remaining = actual_max_chars - used_chars
            if remaining <= 0:
                truncated = True
                break
            if len(row["text"]) > remaining:
                row["text"] = row["text"][:remaining]
                row["truncated"] = True
                truncated = True
            used_chars += len(row["text"])
            evidence.append(EvidenceRecord.model_validate(row))
        return EvidenceResult(
            evidence=evidence,
            used_chars=used_chars,
            max_chars=actual_max_chars,
            truncated=truncated or len(evidence) < len(rows),
        )

    def render_crop(
        self,
        document_id: str,
        *,
        page: int,
        bbox: BBox,
        dpi: int = 144,
    ) -> CropResult:
        if not 72 <= dpi <= 300:
            raise ValueError("dpi must be between 72 and 300")
        pymupdf = load_pymupdf()
        row = self.store.get_document_row(document_id)
        if row["source_suffix"] != ".pdf":
            raise ValueError("render_crop currently supports PDF documents only")
        source_path = Path(row["object_path"])
        with pymupdf.open(source_path) as document:
            if page < 1 or page > document.page_count:
                raise ValueError(f"page must be between 1 and {document.page_count}")
            pdf_page = document[page - 1]
            requested = pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            clip = requested & pdf_page.rect
            if clip.is_empty or clip.width <= 0 or clip.height <= 0:
                raise ValueError("bbox does not intersect the PDF page")
            normalized_bbox = BBox(x0=clip.x0, y0=clip.y0, x1=clip.x1, y1=clip.y1)
            crop_key = sha256_text(
                f"{document_id}:{page}:{clip.x0:.3f}:{clip.y0:.3f}:"
                f"{clip.x1:.3f}:{clip.y1:.3f}:{dpi}"
            )[:16]
            crop_dir = Path(row["artifact_dir"]) / "crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = crop_dir / f"page-{page:05d}-{crop_key}.png"
            cached = artifact_path.exists()
            if not cached:
                scale = dpi / 72
                pixmap = pdf_page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    clip=clip,
                    alpha=False,
                )
                pixmap.save(artifact_path)
            saved = pymupdf.Pixmap(artifact_path)
            width = saved.width
            height = saved.height
        return CropResult(
            document_id=document_id,
            page=page,
            bbox=normalized_bbox,
            dpi=dpi,
            artifact_path=str(artifact_path),
            sha256=sha256_file(artifact_path),
            width=width,
            height=height,
            cached=cached,
        )

    def doctor(self) -> DoctorResult:
        parser_versions = self.router.versions()
        warnings = self.router.diagnostics()
        if not self.store.fts5_available:
            warnings.append("SQLite FTS5 is unavailable; search will use slower LIKE fallback.")
        elif not self.store.trigram_available:
            warnings.append(
                "SQLite trigram tokenizer is unavailable; CJK substring search is limited."
            )
        if self.settings.ocr_provider != "none" and not self.ocr_engine.available:
            warnings.append(
                f"OCR provider {self.settings.ocr_provider} is configured but unavailable."
            )
        return DoctorResult(
            store_root=str(self.settings.store_root),
            database_path=str(self.settings.database_path),
            sqlite_version=sqlite3.sqlite_version,
            fts5_available=self.store.fts5_available,
            trigram_available=self.store.trigram_available,
            parsers=parser_versions,
            ocr_provider=self.ocr_engine.name,
            ocr_available=self.ocr_engine.available,
            warnings=warnings,
        )
