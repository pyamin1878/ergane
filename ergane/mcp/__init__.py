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

from ergane.mcp.prompts import register_prompts
from ergane.mcp.resources import register_resources
from ergane.mcp.tools import register_tools

server = FastMCP(
    "ergane",
    instructions=(
        "Ergane is a web scraping toolkit. Use its tools to extract structured "
        "data from web pages, crawl websites, and leverage built-in presets for "
        "popular sites. All tools are read-only and do not modify any external state."
    ),
    website_url="https://github.com/pyamin1878/ergane",
)
register_tools(server)
register_resources(server)
register_prompts(server)


def run() -> None:
    """Run the MCP server with stdio transport."""
    server.run()
