"""skill-retrieval-mcp: Lightweight MCP Server for RAG-based skill retrieval."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("skill-retrieval-mcp")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0.dev0"
