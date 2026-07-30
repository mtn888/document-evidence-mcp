from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from document_evidence_mcp.config import Settings
from document_evidence_mcp.models import BBox
from document_evidence_mcp.service import DocumentEvidenceService


def create_server(
    settings: Settings | None = None,
    *,
    service: DocumentEvidenceService | None = None,
) -> FastMCP:
    evidence = service or DocumentEvidenceService(settings)
    mcp = FastMCP(
        "document-evidence-mcp",
        instructions=(
            "Import each local document once, search the persistent index, and request "
            "only the evidence or crop needed for the current question. Search results "
            "carry stable evidence IDs, page numbers, bounding boxes and confidence."
        ),
    )

    @mcp.tool()
    def ingest_document(
        path: str,
        languages: list[str] | None = None,
        ocr_mode: Literal["auto", "never", "always"] = "auto",
        force: bool = False,
    ) -> dict[str, Any]:
        """Import a local document once and persist its structured evidence.

        The cache identity includes source SHA-256, parser configuration, OCR provider,
        languages and engine versions. Use force only to create an explicit new revision.
        """

        return evidence.ingest_document(
            path,
            languages=languages,
            ocr_mode=ocr_mode,
            force=force,
        ).model_dump(mode="json")

    @mcp.tool()
    def search_evidence(
        query: str,
        document_id: str | None = None,
        limit: int = 4,
        max_chars: int = 6_000,
    ) -> dict[str, Any]:
        """Search the persistent local index and return a bounded set of citations."""

        return evidence.search_evidence(
            query,
            document_id=document_id,
            limit=limit,
            max_chars=max_chars,
        ).model_dump(mode="json")

    @mcp.tool()
    def get_evidence(
        evidence_ids: list[str],
        max_chars: int = 8_000,
    ) -> dict[str, Any]:
        """Read exact evidence blocks by stable ID under a total character budget."""

        return evidence.get_evidence(
            evidence_ids,
            max_chars=max_chars,
        ).model_dump(mode="json")

    @mcp.tool()
    def list_documents(limit: int = 20) -> list[dict[str, Any]]:
        """List recently indexed document versions without returning document bodies."""

        return [item.model_dump(mode="json") for item in evidence.list_documents(limit=limit)]

    @mcp.tool()
    def get_document(document_id: str) -> dict[str, Any]:
        """Return one document manifest summary and all source paths seen for it."""

        return evidence.get_document(document_id).model_dump(mode="json")

    @mcp.tool()
    def render_crop(
        document_id: str,
        page: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        dpi: int = 144,
    ) -> dict[str, Any]:
        """Render one PDF evidence rectangle to a local PNG artifact.

        Coordinates use PDF points (72 points per inch). This tool returns a path and
        metadata, never the image bytes.
        """

        return evidence.render_crop(
            document_id,
            page=page,
            bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
            dpi=dpi,
        ).model_dump(mode="json")

    @mcp.tool()
    def doctor() -> dict[str, Any]:
        """Report parser, SQLite/FTS and optional OCR availability."""

        return evidence.doctor().model_dump(mode="json")

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
