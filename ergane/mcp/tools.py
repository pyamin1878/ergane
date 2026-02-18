"""MCP tool definitions for Ergane."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import yaml

from ergane.presets import PRESETS, get_preset_schema_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


async def list_presets_tool() -> str:
    """List all available scraping presets with their details.

    Returns a JSON array of presets, each with id, name, description,
    target URL, and available fields.
    """
    results = []
    for preset_id, preset in PRESETS.items():
        schema_path = get_preset_schema_path(preset_id)
        with open(schema_path) as f:
            schema_data = yaml.safe_load(f)
        fields = list(schema_data.get("fields", {}).keys())
        results.append({
            "id": preset_id,
            "name": preset.name,
            "description": preset.description,
            "url": preset.start_urls[0],
            "fields": fields,
        })
    return json.dumps(results, indent=2)


def register_tools(mcp: FastMCP) -> None:
    """Register all Ergane tools with the MCP server."""
    mcp.tool()(list_presets_tool)
