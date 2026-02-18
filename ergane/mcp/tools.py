"""MCP tool definitions for Ergane."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field, create_model

from ergane.crawler.engine import Crawler
from ergane.crawler.fetcher import Fetcher
from ergane.crawler.parser import extract_data, extract_typed_data
from ergane.models import CrawlConfig, CrawlRequest
from ergane.presets import PRESETS, get_preset, get_preset_schema_path
from ergane.schema.yaml_loader import load_schema_from_string, load_schema_from_yaml

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


async def scrape_preset_tool(
    preset: str,
    max_pages: int = 5,
) -> str:
    """Scrape a website using a built-in preset — zero configuration needed.

    Available presets: hacker-news, github-repos, reddit, quotes,
    amazon-products, ebay-listings, wikipedia-articles, bbc-news.

    Use the list_presets tool to see details about each preset.

    Args:
        preset: Preset name (e.g., "hacker-news", "quotes")
        max_pages: Maximum number of pages to scrape (default: 5)

    Returns:
        JSON array of extracted items, or error message.
    """
    try:
        preset_config = get_preset(preset)
        schema_path = get_preset_schema_path(preset)
        schema = load_schema_from_yaml(schema_path)

        async with Crawler(
            urls=preset_config.start_urls,
            schema=schema,
            max_pages=max_pages,
            max_depth=preset_config.defaults.get("max_depth", 1),
            concurrency=5,
            rate_limit=5.0,
            timeout=60.0,
        ) as crawler:
            results = await crawler.run()

        items = [r.model_dump(mode="json") for r in results]
        MAX_ITEMS = 50
        if len(items) > MAX_ITEMS:
            return json.dumps({
                "items": items[:MAX_ITEMS],
                "total": len(items),
                "truncated": True,
            }, indent=2, default=str)
        return json.dumps(items, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)})


async def crawl_tool(
    urls: list[str],
    schema_yaml: str | None = None,
    max_pages: int = 10,
    max_depth: int = 1,
    concurrency: int = 5,
    output_format: str = "json",
) -> str:
    """Crawl one or more websites and extract structured data.

    Starts from the given URLs, follows links up to max_depth, and extracts
    data from each page. Provide a YAML schema to extract specific fields
    using CSS selectors.

    Args:
        urls: Starting URLs to crawl
        schema_yaml: YAML schema for extraction (defines CSS selectors for fields)
        max_pages: Maximum pages to crawl (default: 10)
        max_depth: How deep to follow links (default: 1, 0 = seed URLs only)
        concurrency: Number of concurrent requests (default: 5)
        output_format: Output format — "json", "csv", or "jsonl" (default: "json")

    Returns:
        Extracted data as JSON array, CSV text, or JSONL text.
    """
    try:
        schema = None
        if schema_yaml:
            schema = load_schema_from_string(schema_yaml)

        async with Crawler(
            urls=urls,
            schema=schema,
            max_pages=max_pages,
            max_depth=max_depth,
            concurrency=concurrency,
            rate_limit=5.0,
            timeout=60.0,
        ) as crawler:
            results = await crawler.run()

        items = [r.model_dump(mode="json") for r in results]

        MAX_ITEMS = 50
        truncated = len(items) > MAX_ITEMS

        if output_format == "csv":
            if not items:
                return ""
            import csv
            import io
            display_items = items[:MAX_ITEMS]
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=display_items[0].keys())
            writer.writeheader()
            writer.writerows(display_items)
            text = output.getvalue()
            if truncated:
                text += (
                    f"\n# ... truncated ({len(items)} total items,"
                    f" showing first {MAX_ITEMS})"
                )
            return text

        elif output_format == "jsonl":
            display_items = items[:MAX_ITEMS]
            lines = [json.dumps(item, default=str) for item in display_items]
            text = "\n".join(lines)
            if truncated:
                text += (
                    f"\n// truncated: {len(items)} total items,"
                    f" showing first {MAX_ITEMS}"
                )
            return text

        else:  # json
            if truncated:
                return json.dumps({
                    "items": items[:MAX_ITEMS],
                    "total": len(items),
                    "truncated": True,
                }, indent=2, default=str)
            return json.dumps(items, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)})


def register_tools(mcp: FastMCP) -> None:
    """Register all Ergane tools with the MCP server."""
    mcp.tool()(list_presets_tool)
    mcp.tool()(extract_tool)
    mcp.tool()(scrape_preset_tool)
    mcp.tool()(crawl_tool)
