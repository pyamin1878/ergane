"""MCP resource definitions for Ergane."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import yaml

from ergane.presets import PRESETS, get_preset_schema_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


async def get_preset_resource(name: str) -> str:
    """Get details for a specific scraping preset.

    Args:
        name: The preset identifier (e.g., 'hacker-news', 'quotes')

    Returns:
        JSON string with preset details including name, description,
        target URL, and available fields.
    """
    if name not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"Unknown preset '{name}'. Available: {available}")

    preset = PRESETS[name]
    schema_path = get_preset_schema_path(name)
    with open(schema_path) as f:
        schema_data = yaml.safe_load(f)
    fields = list(schema_data.get("fields", {}).keys())

    return json.dumps({
        "id": name,
        "name": preset.name,
        "description": preset.description,
        "url": preset.start_urls[0],
        "fields": fields,
    }, indent=2)


def register_resources(mcp: FastMCP) -> None:
    """Register all Ergane resources with the MCP server."""
    for preset_id in PRESETS:
        _register_preset_resource(mcp, preset_id)


def _register_preset_resource(mcp: FastMCP, preset_id: str) -> None:
    """Register a single preset as an MCP resource."""

    @mcp.resource(f"preset://{preset_id}")
    async def _resource() -> str:
        return await get_preset_resource(preset_id)
