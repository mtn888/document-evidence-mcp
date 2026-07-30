from __future__ import annotations

import asyncio

from document_evidence_mcp.server import create_server
from document_evidence_mcp.service import DocumentEvidenceService


def test_mcp_server_exposes_bounded_evidence_tools(
    service: DocumentEvidenceService,
) -> None:
    server = create_server(service=service)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "doctor",
        "get_document",
        "get_evidence",
        "ingest_document",
        "list_documents",
        "render_crop",
        "search_evidence",
    }


def test_mcp_doctor_returns_structured_output(
    service: DocumentEvidenceService,
) -> None:
    server = create_server(service=service)
    result = asyncio.run(server.call_tool("doctor", {}))

    assert isinstance(result, tuple)
    content, structured = result
    assert content
    assert structured["fts5_available"] is True
    assert structured["ocr_provider"] == "none"
