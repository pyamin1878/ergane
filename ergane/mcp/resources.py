"""MCP resource definitions for Ergane."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_resources(mcp: FastMCP) -> None:
    """Register all Ergane resources with the MCP server."""
    pass
