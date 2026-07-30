from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_server_initializes_and_calls_tool(tmp_path: Path) -> None:
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "document_evidence_mcp.server"],
            cwd=str(Path(__file__).parents[1]),
            env={
                **os.environ,
                "DOCUMENT_EVIDENCE_STORE": str(tmp_path / "stdio-store"),
                "DOCUMENT_EVIDENCE_OCR_PROVIDER": "none",
            },
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("doctor", {})

        assert "search_evidence" in {tool.name for tool in tools.tools}
        assert result.isError is False
        assert result.structuredContent["fts5_available"] is True
        assert result.structuredContent["ocr_provider"] == "none"

    asyncio.run(exercise())
