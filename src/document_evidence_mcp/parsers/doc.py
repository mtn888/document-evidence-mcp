from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from zipfile import BadZipFile, ZipFile, is_zipfile

from document_evidence_mcp.models import ParseResult
from document_evidence_mcp.parsers.base import ParseContext
from document_evidence_mcp.parsers.docx import DocxParser


class DocConversionError(RuntimeError):
    """Raised when a legacy Word document cannot be converted safely."""


# Bump this whenever the PowerShell conversion behavior changes so old derivatives are ignored.
CONVERTER_VERSION = "2"
DERIVED_DOCX_NAME = f"derived-word-com-v{CONVERTER_VERSION}.docx"


def _word_com_diagnostic() -> str | None:
    if os.name != "nt":
        return "legacy .doc conversion requires Windows and Microsoft Word"
    if shutil.which("powershell.exe") is None:
        return "Windows PowerShell 5.1 (powershell.exe) is unavailable"

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
            pass
    except (ImportError, OSError):
        return "Microsoft Word COM registration was not found"
    return None


def _convert_doc_to_docx(
    source: Path,
    destination: Path,
    *,
    timeout_seconds: int,
) -> None:
    if diagnostic := _word_com_diagnostic():
        raise DocConversionError(f"cannot convert legacy .doc: {diagnostic}")

    script = Path(__file__).with_name("convert_doc_to_docx.ps1")
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-SourcePath",
        str(source),
        "-DestinationPath",
        str(destination),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocConversionError(
            f"Microsoft Word conversion timed out after {timeout_seconds} seconds"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown conversion error"
        raise DocConversionError(
            f"Microsoft Word could not convert legacy .doc (exit {completed.returncode}): {detail}"
        )
    if not destination.is_file() or not is_zipfile(destination):
        raise DocConversionError("Microsoft Word did not produce a valid DOCX container")


def _is_valid_docx_cache(path: Path) -> bool:
    if not path.is_file() or not is_zipfile(path):
        return False
    try:
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            return archive.testzip() is None and {
                "[Content_Types].xml",
                "word/document.xml",
            }.issubset(names)
    except (BadZipFile, OSError):
        return False


class DocParser:
    name = "word-com+python-docx"
    version = f"{CONVERTER_VERSION}+python-docx-{version('python-docx')}"
    shared_cache_key = f"word-com-v{CONVERTER_VERSION}"
    extensions = frozenset({".doc"})

    def parse(self, context: ParseContext) -> ParseResult:
        cached = context.source_path.with_name(DERIVED_DOCX_NAME)
        if _is_valid_docx_cache(cached):
            return self._parse_converted(context, cached)
        cached.unlink(missing_ok=True)

        converted = context.work_dir / "converted-source.docx"
        try:
            _convert_doc_to_docx(
                context.source_path,
                converted,
                timeout_seconds=context.settings.doc_conversion_timeout_seconds,
            )
            result = self._parse_converted(context, converted)
            try:
                os.replace(converted, cached)
            except OSError:
                if not _is_valid_docx_cache(cached):
                    raise
            return result
        finally:
            converted.unlink(missing_ok=True)

    def _parse_converted(self, context: ParseContext, converted: Path) -> ParseResult:
        result = DocxParser().parse(replace(context, source_path=converted))
        blocks = [
            block.model_copy(
                update={
                    "parser": self.name,
                    "metadata": {
                        **block.metadata,
                        "source_format": "doc",
                        "conversion": "microsoft-word-com",
                    },
                }
            )
            for block in result.blocks
        ]
        return result.model_copy(
            update={
                "parser": self.name,
                "parser_version": self.version,
                "blocks": blocks,
            }
        )

    @staticmethod
    def diagnostic() -> str | None:
        return _word_com_diagnostic()
