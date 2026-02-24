"""MCP tool definitions for Ergane."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import yaml
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, create_model

from ergane.crawler.engine import Crawler
from ergane.crawler.hooks import AuthHeaderHook
from ergane.crawler.parser import extract_data, extract_typed_data
from ergane.models import CrawlConfig, CrawlRequest
from ergane.presets import PRESETS, get_preset, get_preset_schema_path
from ergane.schema.yaml_loader import load_schema_from_string, load_schema_from_yaml

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

MAX_RESULT_ITEMS = 50


def _get_fetcher_cls(js: bool):
    """Return PlaywrightFetcher if js=True, else Fetcher."""
    if js:
        from ergane.crawler.playwright_fetcher import PlaywrightFetcher
        return PlaywrightFetcher
    from ergane.crawler.fetcher import Fetcher
    return Fetcher


def _error(message: str, code: str) -> str:
    """Return a JSON error response with a machine-readable code.

    Codes let callers distinguish categories of failure:
    - FETCH_ERROR      — network/HTTP problem
    - INVALID_PRESET   — unknown preset name
    - SCHEMA_ERROR     — YAML schema parse failure
    - INVALID_PARAMS   — bad parameter values
    - INTERNAL_ERROR   — unexpected exception
    """
    return json.dumps({"error": message, "error_code": code})


def _truncate_json(items: list, max_items: int) -> str:
    """Return a JSON string, truncating *items* to *max_items*.

    When truncated, wraps the result in an envelope object with
    ``total`` and ``truncated`` metadata so callers know the full count.
    """
    if len(items) <= max_items:
        return json.dumps(items, indent=2, default=str)
    return json.dumps(
        {"items": items[:max_items], "total": len(items), "truncated": True},
        indent=2,
        default=str,
    )


def _load_all_preset_fields() -> dict[str, list[str]]:
    """Preload field names for every preset at import time (static YAML files)."""
    result: dict[str, list[str]] = {}
    for preset_id in PRESETS:
        try:
            schema_path = get_preset_schema_path(preset_id)
            with open(schema_path) as f:
                schema_data = yaml.safe_load(f)
            result[preset_id] = list(schema_data.get("fields", {}).keys())
        except Exception:
            result[preset_id] = []
    return result


# Loaded once at import; avoids repeated synchronous file I/O inside async callers.
_PRESET_FIELDS: dict[str, list[str]] = _load_all_preset_fields()


def _get_preset_fields(preset_id: str) -> list[str]:
    """Return cached field names for a preset."""
    return _PRESET_FIELDS.get(preset_id, [])


async def _ctx_info(ctx: Context | None, msg: str) -> None:
    """Log info via MCP context if available."""
    if ctx is not None:
        try:
            await ctx.info(msg)
        except Exception:
            pass


async def _ctx_warning(ctx: Context | None, msg: str) -> None:
    """Log warning via MCP context if available."""
    if ctx is not None:
        try:
            await ctx.warning(msg)
        except Exception:
            pass


async def _ctx_progress(
    ctx: Context | None, current: float, total: float, msg: str,
) -> None:
    """Report progress via MCP context if available."""
    if ctx is not None:
        try:
            await ctx.report_progress(current, total, msg)
        except Exception:
            pass


async def list_presets_tool() -> str:
    """List all available scraping presets with their details.

    Returns a JSON array of presets, each with id, name, description,
    target URL, and available fields.
    """
    results = []
    for preset_id, preset in PRESETS.items():
        fields = _get_preset_fields(preset_id)
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
        "url": (str, ...),  # type: ignore[dict-item]
        "crawled_at": (datetime, ...),  # type: ignore[dict-item]
    }
    for name, css in selectors.items():
        field_definitions[name] = (
            str,
            Field(json_schema_extra={"selector": css, "coerce": False, "attr": None}),
        )
    return create_model("SelectorSchema", **field_definitions)  # type: ignore[call-overload, no-any-return]


async def extract_tool(
    url: str,
    selectors: dict[str, str] | None = None,
    schema_yaml: str | None = None,
    js: bool = False,
    js_wait: str = "networkidle",
    timeout: float = 60.0,
    proxy: str | None = None,
    headers: dict[str, str] | None = None,
    ctx: Context | None = None,
) -> str:
    """Extract structured data from a single web page.

    Fetches the URL and extracts data using CSS selectors. Provide either
    a simple selector mapping or a full YAML schema.

    Args:
        url: The URL to scrape
        selectors: Map of field names to CSS selectors
            (e.g., {"title": "h1", "price": ".price"})
        schema_yaml: Full YAML schema definition (alternative to selectors)
        js: Enable JavaScript rendering via Playwright
        js_wait: Playwright page wait strategy
        timeout: Request timeout in seconds (default: 60)
        proxy: HTTP/HTTPS proxy URL
        headers: Custom HTTP headers to send with the request

    Returns:
        JSON string with extracted data.
    """
    if timeout <= 0:
        return _error("timeout must be > 0", "INVALID_PARAMS")

    try:
        schema = None
        if schema_yaml:
            try:
                schema = load_schema_from_string(schema_yaml)
            except Exception as e:
                return _error(f"Invalid schema YAML: {e}", "SCHEMA_ERROR")
        elif selectors:
            schema = _build_selector_schema(selectors)

        config = CrawlConfig(
            max_requests_per_second=10.0,
            max_concurrent_requests=1,
            request_timeout=timeout,
            proxy=proxy,
            js=js,
            js_wait=js_wait,
        )
        request = CrawlRequest(
            url=url,
            depth=0,
            priority=0,
            metadata={"headers": headers} if headers else {},
        )

        await _ctx_info(ctx, f"Fetching {url}")

        fetcher_cls = _get_fetcher_cls(js)
        async with fetcher_cls(config) as fetcher:
            response = await fetcher.fetch(request)

        if response.error:
            await _ctx_warning(ctx, f"Fetch failed for {url}: {response.error}")
            return _error(f"Fetch failed: {response.error}", "FETCH_ERROR")

        if not response.content:
            await _ctx_warning(ctx, f"Empty response from {url}")
            return _error("Empty response", "FETCH_ERROR")

        if schema is not None:
            item = extract_typed_data(response, schema)
        else:
            item = extract_data(response)

        await _ctx_info(ctx, f"Extracted data from {url}")
        return json.dumps(item.model_dump(mode="json"), indent=2, default=str)

    except Exception as e:
        return _error(str(e), "INTERNAL_ERROR")


async def scrape_preset_tool(
    preset: str,
    max_pages: int = 5,
    js: bool = False,
    js_wait: str = "networkidle",
    timeout: float = 60.0,
    ctx: Context | None = None,
) -> str:
    """Scrape a website using a built-in preset — zero configuration needed.

    Available presets: hacker-news, github-repos, reddit, quotes,
    amazon-products, ebay-listings, wikipedia-articles, bbc-news.

    Use the list_presets tool to see details about each preset.

    Args:
        preset: Preset name (e.g., "hacker-news", "quotes")
        max_pages: Maximum number of pages to scrape (default: 5)
        js: Enable JavaScript rendering via Playwright
        js_wait: Playwright page wait strategy
        timeout: Request timeout in seconds (default: 60)

    Returns:
        JSON array of extracted items, or error message.
    """
    if max_pages < 1:
        return _error("max_pages must be >= 1", "INVALID_PARAMS")
    if timeout <= 0:
        return _error("timeout must be > 0", "INVALID_PARAMS")

    try:
        preset_config = get_preset(preset)
    except KeyError as e:
        return _error(str(e), "INVALID_PRESET")

    try:
        schema_path = get_preset_schema_path(preset)
        schema = load_schema_from_yaml(schema_path)

        async with Crawler(
            urls=preset_config.start_urls,
            schema=schema,
            max_pages=max_pages,
            max_depth=preset_config.defaults.get("max_depth", 1),
            concurrency=5,
            rate_limit=5.0,
            timeout=timeout,
            js=js,
            js_wait=js_wait,
        ) as crawler:
            results = []
            async for item in crawler.stream():
                stats = crawler.stats
                await _ctx_progress(
                    ctx, stats["pages_crawled"], max_pages,
                    f"Scraping {preset}... ({stats['pages_crawled']}/{max_pages})",
                )
                results.append(item)

            stats = crawler.stats
            if stats["errors"] > 0:
                await _ctx_warning(ctx, f"Finished with {stats['errors']} error(s)")
            await _ctx_info(
                ctx,
                f"Scrape complete: {stats['pages_crawled']} pages, "
                f"{stats['items_extracted']} items",
            )

        items = [r.model_dump(mode="json") for r in results]
        return _truncate_json(items, MAX_RESULT_ITEMS)

    except Exception as e:
        return _error(str(e), "INTERNAL_ERROR")


async def crawl_tool(
    urls: list[str],
    schema_yaml: str | None = None,
    max_pages: int = 10,
    max_depth: int = 1,
    concurrency: int = 5,
    output_format: str = "json",
    js: bool = False,
    js_wait: str = "networkidle",
    rate_limit: float = 5.0,
    timeout: float = 60.0,
    same_domain: bool = True,
    ignore_robots: bool = False,
    proxy: str | None = None,
    headers: dict[str, str] | None = None,
    ctx: Context | None = None,
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
        js: Enable JavaScript rendering via Playwright
        js_wait: Playwright page wait strategy
        rate_limit: Maximum requests per second per domain (default: 5)
        timeout: Request timeout in seconds (default: 60)
        same_domain: Only follow links on the same domain (default: true)
        ignore_robots: Ignore robots.txt restrictions (default: false)
        proxy: HTTP/HTTPS proxy URL
        headers: Custom HTTP headers to send with requests

    Returns:
        Extracted data as JSON array, CSV text, or JSONL text.
    """
    if max_pages < 1:
        return _error("max_pages must be >= 1", "INVALID_PARAMS")
    if concurrency < 1:
        return _error("concurrency must be >= 1", "INVALID_PARAMS")
    if rate_limit <= 0:
        return _error("rate_limit must be > 0", "INVALID_PARAMS")
    if timeout <= 0:
        return _error("timeout must be > 0", "INVALID_PARAMS")

    try:
        schema = None
        if schema_yaml:
            try:
                schema = load_schema_from_string(schema_yaml)
            except Exception as e:
                return _error(f"Invalid schema YAML: {e}", "SCHEMA_ERROR")

        hooks = []
        if headers:
            hooks.append(AuthHeaderHook(headers))

        async with Crawler(
            urls=urls,
            schema=schema,
            max_pages=max_pages,
            max_depth=max_depth,
            concurrency=concurrency,
            rate_limit=rate_limit,
            timeout=timeout,
            same_domain=same_domain,
            respect_robots_txt=not ignore_robots,
            proxy=proxy,
            hooks=hooks or None,
            js=js,
            js_wait=js_wait,
        ) as crawler:
            results = []
            async for item in crawler.stream():
                stats = crawler.stats
                await _ctx_progress(
                    ctx, stats["pages_crawled"], max_pages,
                    f"Crawling... ({stats['pages_crawled']}/{max_pages} pages)",
                )
                results.append(item)

            stats = crawler.stats
            if stats["errors"] > 0:
                await _ctx_warning(ctx, f"Finished with {stats['errors']} error(s)")
            await _ctx_info(
                ctx,
                f"Crawl complete: {stats['pages_crawled']} pages, "
                f"{stats['items_extracted']} items",
            )

        items = [r.model_dump(mode="json") for r in results]
        display_items = items[:MAX_RESULT_ITEMS]

        if output_format == "csv":
            if not items:
                return ""
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=display_items[0].keys())
            writer.writeheader()
            writer.writerows(display_items)
            return output.getvalue()

        elif output_format == "jsonl":
            lines = [json.dumps(item, default=str) for item in display_items]
            return "\n".join(lines)

        else:  # json
            return _truncate_json(items, MAX_RESULT_ITEMS)

    except Exception as e:
        return _error(str(e), "INTERNAL_ERROR")


def register_tools(mcp: FastMCP) -> None:
    """Register all Ergane tools with the MCP server."""
    mcp.tool(
        title="List Presets",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )(list_presets_tool)
    mcp.tool(
        title="Extract Page Data",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )(extract_tool)
    mcp.tool(
        title="Scrape with Preset",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )(scrape_preset_tool)
    mcp.tool(
        title="Crawl Website",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )(crawl_tool)
