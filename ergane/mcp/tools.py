"""MCP tool definitions for Ergane."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field, create_model

from ergane.crawler.fetcher import Fetcher
from ergane.crawler.parser import extract_data, extract_typed_data
from ergane.models import CrawlConfig, CrawlRequest
from ergane.presets import PRESETS, get_preset_schema_path
from ergane.schema.yaml_loader import load_schema_from_string

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


def _build_selector_schema(selectors: dict[str, str]) -> type[BaseModel]:
    """Build a Pydantic model from a simple selector mapping."""
    field_definitions: dict[str, tuple[type, ...]] = {
        "url": (str, ...),
        "crawled_at": (datetime, ...),
    }
    for name, css in selectors.items():
        field_definitions[name] = (
            str,
            Field(json_schema_extra={"selector": css, "coerce": False, "attr": None}),
        )
    return create_model("SelectorSchema", **field_definitions)


async def extract_tool(
    url: str,
    selectors: dict[str, str] | None = None,
    schema_yaml: str | None = None,
) -> str:
    """Extract structured data from a single web page.

    Fetches the URL and extracts data using CSS selectors. Provide either
    a simple selector mapping or a full YAML schema.

    Args:
        url: The URL to scrape
        selectors: Map of field names to CSS selectors
            (e.g., {"title": "h1", "price": ".price"})
        schema_yaml: Full YAML schema definition (alternative to selectors)

    Returns:
        JSON string with extracted data.
    """
    try:
        schema = None
        if schema_yaml:
            schema = load_schema_from_string(schema_yaml)
        elif selectors:
            schema = _build_selector_schema(selectors)

        config = CrawlConfig(
            max_requests_per_second=10.0,
            max_concurrent_requests=1,
            request_timeout=60.0,
        )
        request = CrawlRequest(url=url, depth=0, priority=0)

        async with Fetcher(config) as fetcher:
            response = await fetcher.fetch(request)

        if response.error:
            return json.dumps({"error": f"Fetch failed: {response.error}"})

        if not response.content:
            return json.dumps({"error": "Empty response"})

        if schema is not None:
            item = extract_typed_data(response, schema)
        else:
            item = extract_data(response)

        return json.dumps(item.model_dump(mode="json"), indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)})


def register_tools(mcp: FastMCP) -> None:
    """Register all Ergane tools with the MCP server."""
    mcp.tool()(list_presets_tool)
    mcp.tool()(extract_tool)
