from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_store_root() -> Path:
    configured = os.environ.get("DOCUMENT_EVIDENCE_STORE")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "document-evidence-mcp"
    return Path.home() / ".local" / "share" / "document-evidence-mcp"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _allowed_roots_from_env() -> tuple[Path, ...]:
    raw = os.environ.get("DOCUMENT_EVIDENCE_ALLOWED_ROOTS", "").strip()
    if not raw:
        return ()
    return tuple(Path(item).expanduser().resolve() for item in raw.split(os.pathsep) if item)


@dataclass(frozen=True, slots=True)
class Settings:
    store_root: Path = field(default_factory=_default_store_root)
    allowed_roots: tuple[Path, ...] = field(default_factory=_allowed_roots_from_env)
    max_file_bytes: int = field(
        default_factory=lambda: _env_int(
            "DOCUMENT_EVIDENCE_MAX_FILE_BYTES",
            1_073_741_824,
        )
    )
    chunk_chars: int = field(
        default_factory=lambda: _env_int("DOCUMENT_EVIDENCE_CHUNK_CHARS", 1_600)
    )
    chunk_overlap: int = field(
        default_factory=lambda: _env_int("DOCUMENT_EVIDENCE_CHUNK_OVERLAP", 160)
    )
    doc_conversion_timeout_seconds: int = field(
        default_factory=lambda: _env_int(
            "DOCUMENT_EVIDENCE_DOC_CONVERSION_TIMEOUT_SECONDS",
            300,
        )
    )
    max_search_chars: int = field(
        default_factory=lambda: _env_int("DOCUMENT_EVIDENCE_MAX_SEARCH_CHARS", 12_000)
    )
    max_search_hits: int = field(
        default_factory=lambda: _env_int("DOCUMENT_EVIDENCE_MAX_SEARCH_HITS", 20)
    )
    ocr_provider: str = field(
        default_factory=lambda: os.environ.get(
            "DOCUMENT_EVIDENCE_OCR_PROVIDER",
            "none",
        ).lower()
    )

    @property
    def database_path(self) -> Path:
        return self.store_root / "index.sqlite"

    @property
    def object_root(self) -> Path:
        return self.store_root / "objects"

    @property
    def version_root(self) -> Path:
        return self.store_root / "versions"

    def ensure_directories(self) -> None:
        self.store_root.mkdir(parents=True, exist_ok=True)
        self.object_root.mkdir(parents=True, exist_ok=True)
        self.version_root.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if self.chunk_chars < 200:
            raise ValueError("chunk_chars must be at least 200")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_chars:
            raise ValueError("chunk_overlap must be non-negative and less than chunk_chars")
        if self.doc_conversion_timeout_seconds <= 0:
            raise ValueError("doc_conversion_timeout_seconds must be positive")
        if self.max_search_chars < 200:
            raise ValueError("max_search_chars must be at least 200")
        if self.max_search_hits < 1:
            raise ValueError("max_search_hits must be positive")
        if self.ocr_provider not in {"none", "paddleocr"}:
            raise ValueError("DOCUMENT_EVIDENCE_OCR_PROVIDER must be none or paddleocr")

    def resolve_input_file(self, value: str | Path) -> Path:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"not a regular file: {path}")
        size = path.stat().st_size
        if size > self.max_file_bytes:
            raise ValueError(
                f"file is {size} bytes, above DOCUMENT_EVIDENCE_MAX_FILE_BYTES="
                f"{self.max_file_bytes}"
            )
        if self.allowed_roots and not any(path.is_relative_to(root) for root in self.allowed_roots):
            roots = ", ".join(str(root) for root in self.allowed_roots)
            raise PermissionError(f"path is outside DOCUMENT_EVIDENCE_ALLOWED_ROOTS: {roots}")
        return path
