"""Persistent, token-budgeted document evidence for MCP clients."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("document-evidence-mcp")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["__version__"]
