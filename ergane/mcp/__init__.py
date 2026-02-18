"""Ergane MCP server — expose web scraping tools to LLMs.

Requires the MCP SDK: pip install ergane[mcp]
"""

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as err:
    raise ImportError(
        "The MCP SDK is required for the Ergane MCP server. "
        "Install it with: pip install ergane[mcp]"
    ) from err

from ergane.mcp.resources import register_resources
from ergane.mcp.tools import register_tools

server = FastMCP("ergane")
register_tools(server)
register_resources(server)


def run() -> None:
    """Run the MCP server with stdio transport."""
    server.run()
