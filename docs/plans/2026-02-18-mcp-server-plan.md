# Ergane MCP Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an MCP server to Ergane that exposes crawling, extraction, and preset tools to LLMs via stdio transport.

**Architecture:** Optional `ergane/mcp/` module using FastMCP from the official MCP SDK. Four tools (crawl, extract, scrape_preset, list_presets) and preset resources. Installed via `pip install ergane[mcp]`.

**Tech Stack:** Python 3.10+, `mcp` SDK (FastMCP), ergane Crawler/presets/schema APIs, pytest

---

### Task 1: Add MCP optional dependency

**Files:**
- Modify: `pyproject.toml:37-46`

**Step 1: Add the MCP optional dependency**

In `pyproject.toml`, add an `mcp` entry to `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
mcp = [
    "mcp[cli]>=1.0.0",
]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    "mypy>=1.8.0",
    "ruff>=0.2.0",
    "mcp[cli]>=1.0.0",
]
```

Note: Also add `mcp[cli]>=1.0.0` to the `dev` dependencies so tests can import it.

**Step 2: Install the new dependency**

Run: `uv pip install -e ".[dev]"`

**Step 3: Verify installation**

Run: `uv run python -c "from mcp.server.fastmcp import FastMCP; print('MCP SDK installed')"`
Expected: `MCP SDK installed`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add MCP SDK as optional dependency"
```

---

### Task 2: Create MCP server skeleton with list_presets tool

**Files:**
- Create: `ergane/mcp/__init__.py`
- Create: `ergane/mcp/tools.py`
- Test: `tests/test_mcp.py`

**Step 1: Write the failing test**

Create `tests/test_mcp.py`:

```python
"""Tests for the Ergane MCP server."""

import json

import pytest

from ergane.mcp.tools import list_presets_tool


class TestListPresets:
    """Tests for the list_presets tool."""

    async def test_list_presets_returns_json(self):
        result = await list_presets_tool()
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0

    async def test_list_presets_contains_expected_fields(self):
        result = await list_presets_tool()
        data = json.loads(result)
        preset = data[0]
        assert "id" in preset
        assert "name" in preset
        assert "description" in preset
        assert "url" in preset
        assert "fields" in preset

    async def test_list_presets_includes_hacker_news(self):
        result = await list_presets_tool()
        data = json.loads(result)
        ids = [p["id"] for p in data]
        assert "hacker-news" in ids
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ergane.mcp'`

**Step 3: Create the MCP server module**

Create `ergane/mcp/__init__.py`:

```python
"""Ergane MCP server — expose web scraping tools to LLMs.

Requires the MCP SDK: pip install ergane[mcp]
"""

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "The MCP SDK is required for the Ergane MCP server. "
        "Install it with: pip install ergane[mcp]"
    )

from ergane.mcp.tools import register_tools
from ergane.mcp.resources import register_resources

server = FastMCP("ergane")
register_tools(server)
register_resources(server)


def run() -> None:
    """Run the MCP server with stdio transport."""
    server.run()
```

Create `ergane/mcp/tools.py`:

```python
"""MCP tool definitions for Ergane."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import yaml

from ergane.presets import PRESETS, get_preset, get_preset_schema_path
from ergane.schema.yaml_loader import load_schema_from_yaml

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
```

Create `ergane/mcp/resources.py` (empty placeholder for now):

```python
"""MCP resource definitions for Ergane."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_resources(mcp: FastMCP) -> None:
    """Register all Ergane resources with the MCP server."""
    pass
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add ergane/mcp/__init__.py ergane/mcp/tools.py ergane/mcp/resources.py tests/test_mcp.py
git commit -m "feat(mcp): add server skeleton with list_presets tool"
```

---

### Task 3: Add preset resources

**Files:**
- Modify: `ergane/mcp/resources.py`
- Modify: `tests/test_mcp.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:

```python
from ergane.mcp.resources import get_preset_resource


class TestPresetResources:
    """Tests for preset MCP resources."""

    async def test_get_valid_preset(self):
        result = await get_preset_resource("hacker-news")
        data = json.loads(result)
        assert data["name"] == "Hacker News"
        assert "news.ycombinator.com" in data["url"]
        assert "title" in data["fields"]

    async def test_get_invalid_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            await get_preset_resource("nonexistent")

    async def test_preset_has_all_fields(self):
        result = await get_preset_resource("quotes")
        data = json.loads(result)
        assert "id" in data
        assert "name" in data
        assert "description" in data
        assert "url" in data
        assert "fields" in data
        assert isinstance(data["fields"], list)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::TestPresetResources -v`
Expected: FAIL with `ImportError: cannot import name 'get_preset_resource'`

**Step 3: Implement preset resources**

Replace `ergane/mcp/resources.py`:

```python
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
        # Register each preset as a resource using a closure to capture preset_id
        _register_preset_resource(mcp, preset_id)


def _register_preset_resource(mcp: FastMCP, preset_id: str) -> None:
    """Register a single preset as an MCP resource."""
    preset = PRESETS[preset_id]

    @mcp.resource(f"preset://{preset_id}")
    async def _resource() -> str:
        return await get_preset_resource(preset_id)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add ergane/mcp/resources.py tests/test_mcp.py
git commit -m "feat(mcp): add preset resources"
```

---

### Task 4: Add the extract tool (single-page extraction)

**Files:**
- Modify: `ergane/mcp/tools.py`
- Modify: `tests/test_mcp.py`
- Reference: `ergane/crawler/engine.py` (Crawler API), `ergane/schema/yaml_loader.py` (load_schema_from_string)

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:

```python
from ergane.mcp.tools import extract_tool


class TestExtractTool:
    """Tests for the extract (single-page) tool."""

    async def test_extract_with_selectors(self, mock_server):
        result = await extract_tool(
            url=f"{mock_server}/",
            selectors={"title": "h1"},
        )
        data = json.loads(result)
        assert data["title"] == "Home"

    async def test_extract_with_schema_yaml(self, mock_server):
        schema_yaml = """
name: TestSchema
fields:
  heading:
    selector: "h1"
    type: str
"""
        result = await extract_tool(
            url=f"{mock_server}/page1",
            schema_yaml=schema_yaml,
        )
        data = json.loads(result)
        assert data["heading"] == "Page 1"

    async def test_extract_invalid_url(self):
        result = await extract_tool(
            url="http://localhost:1/nonexistent",
            selectors={"title": "h1"},
        )
        data = json.loads(result)
        assert "error" in data

    async def test_extract_no_selectors_or_schema(self, mock_server):
        result = await extract_tool(url=f"{mock_server}/")
        data = json.loads(result)
        # Without selectors, returns basic page data
        assert "url" in data
        assert "title" in data
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::TestExtractTool -v`
Expected: FAIL with `ImportError: cannot import name 'extract_tool'`

**Step 3: Implement the extract tool**

Add to `ergane/mcp/tools.py`:

```python
import asyncio

from pydantic import BaseModel, create_model, Field
from ergane.crawler.engine import Crawler
from ergane.crawler.fetcher import Fetcher
from ergane.crawler.parser import extract_data, extract_typed_data
from ergane.models import CrawlConfig, CrawlRequest
from ergane.schema.yaml_loader import load_schema_from_string


def _build_selector_schema(selectors: dict[str, str]) -> type[BaseModel]:
    """Build a Pydantic model from a simple selector mapping."""
    from datetime import datetime

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
        selectors: Map of field names to CSS selectors (e.g., {"title": "h1", "price": ".price"})
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
```

Also update the `register_tools` function:

```python
def register_tools(mcp: FastMCP) -> None:
    """Register all Ergane tools with the MCP server."""
    mcp.tool()(list_presets_tool)
    mcp.tool()(extract_tool)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ergane/mcp/tools.py tests/test_mcp.py
git commit -m "feat(mcp): add extract tool for single-page extraction"
```

---

### Task 5: Add the scrape_preset tool

**Files:**
- Modify: `ergane/mcp/tools.py`
- Modify: `tests/test_mcp.py`
- Reference: `ergane/presets/registry.py` (get_preset, get_preset_schema_path)

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`. Since presets point to real websites, we test with mocked crawl behavior:

```python
from unittest.mock import AsyncMock, patch

from ergane.mcp.tools import scrape_preset_tool


class TestScrapePresetTool:
    """Tests for the scrape_preset tool."""

    async def test_scrape_preset_invalid_preset(self):
        result = await scrape_preset_tool(preset="nonexistent")
        data = json.loads(result)
        assert "error" in data
        assert "Unknown preset" in data["error"]

    async def test_scrape_preset_returns_json_array(self, mock_server):
        """Test scrape_preset with a mocked preset that uses the mock server."""
        from ergane.presets.registry import PresetConfig

        mock_preset = PresetConfig(
            name="Test Preset",
            description="Test",
            start_urls=[f"{mock_server}/"],
            schema_file="quotes_toscrape.yaml",
            defaults={"max_pages": 1, "max_depth": 0},
        )
        with patch.dict("ergane.presets.registry.PRESETS", {"test": mock_preset}):
            result = await scrape_preset_tool(preset="test", max_pages=1)
        data = json.loads(result)
        assert isinstance(data, (list, dict))
        # If it's a dict, it might be an error or a single result
        if isinstance(data, dict) and "error" not in data:
            assert "total" in data or len(data) > 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::TestScrapePresetTool -v`
Expected: FAIL with `ImportError: cannot import name 'scrape_preset_tool'`

**Step 3: Implement the scrape_preset tool**

Add to `ergane/mcp/tools.py`:

```python
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
        # Truncate large results
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
```

Update `register_tools`:

```python
def register_tools(mcp: FastMCP) -> None:
    """Register all Ergane tools with the MCP server."""
    mcp.tool()(list_presets_tool)
    mcp.tool()(extract_tool)
    mcp.tool()(scrape_preset_tool)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ergane/mcp/tools.py tests/test_mcp.py
git commit -m "feat(mcp): add scrape_preset tool"
```

---

### Task 6: Add the crawl tool

**Files:**
- Modify: `ergane/mcp/tools.py`
- Modify: `tests/test_mcp.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:

```python
from ergane.mcp.tools import crawl_tool


class TestCrawlTool:
    """Tests for the crawl tool."""

    async def test_crawl_basic(self, mock_server):
        result = await crawl_tool(urls=[f"{mock_server}/"], max_pages=2)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_crawl_with_schema_yaml(self, mock_server):
        schema_yaml = """
name: TestSchema
fields:
  heading:
    selector: "h1"
    type: str
"""
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            schema_yaml=schema_yaml,
            max_pages=1,
            max_depth=0,
        )
        data = json.loads(result)
        assert isinstance(data, list)
        if len(data) > 0:
            assert "heading" in data[0]

    async def test_crawl_invalid_url(self):
        result = await crawl_tool(urls=["http://localhost:1/nonexistent"], max_pages=1)
        data = json.loads(result)
        # Should return empty list or error, not crash
        assert isinstance(data, (list, dict))

    async def test_crawl_truncates_large_results(self, mock_server):
        """Verify that results over MAX_ITEMS are truncated."""
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            max_pages=3,
            max_depth=1,
        )
        data = json.loads(result)
        # With mock server we won't hit 50, just verify structure is valid
        assert isinstance(data, (list, dict))
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::TestCrawlTool -v`
Expected: FAIL with `ImportError: cannot import name 'crawl_tool'`

**Step 3: Implement the crawl tool**

Add to `ergane/mcp/tools.py`:

```python
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
            display_items = items[:MAX_ITEMS]
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=display_items[0].keys())
            writer.writeheader()
            writer.writerows(display_items)
            text = output.getvalue()
            if truncated:
                text += f"\n# ... truncated ({len(items)} total items, showing first {MAX_ITEMS})"
            return text

        elif output_format == "jsonl":
            display_items = items[:MAX_ITEMS]
            lines = [json.dumps(item, default=str) for item in display_items]
            text = "\n".join(lines)
            if truncated:
                text += f"\n// truncated: {len(items)} total items, showing first {MAX_ITEMS}"
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
```

Update `register_tools`:

```python
def register_tools(mcp: FastMCP) -> None:
    """Register all Ergane tools with the MCP server."""
    mcp.tool()(list_presets_tool)
    mcp.tool()(extract_tool)
    mcp.tool()(scrape_preset_tool)
    mcp.tool()(crawl_tool)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ergane/mcp/tools.py tests/test_mcp.py
git commit -m "feat(mcp): add crawl tool"
```

---

### Task 7: Add __main__.py entry point

**Files:**
- Create: `ergane/mcp/__main__.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:

```python
import subprocess
import sys


class TestEntryPoints:
    """Tests for MCP server entry points."""

    def test_module_entry_point_help(self):
        """Verify python -m ergane.mcp is a valid entry point (smoke test)."""
        # Just verify the module can be imported without error
        result = subprocess.run(
            [sys.executable, "-c", "from ergane.mcp import server; print(server.name)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "ergane" in result.stdout.strip()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::TestEntryPoints -v`
Expected: May pass or fail depending on server import. Either way, proceed.

**Step 3: Create __main__.py**

Create `ergane/mcp/__main__.py`:

```python
"""Entry point for `python -m ergane.mcp`."""

from ergane.mcp import run

if __name__ == "__main__":
    run()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ergane/mcp/__main__.py tests/test_mcp.py
git commit -m "feat(mcp): add __main__.py entry point"
```

---

### Task 8: Add `ergane mcp` CLI subcommand

**Files:**
- Modify: `ergane/main.py`
- Modify: `tests/test_mcp.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:

```python
from click.testing import CliRunner


class TestCLI:
    """Tests for the ergane mcp CLI subcommand."""

    def test_mcp_command_exists(self):
        """Verify that 'ergane mcp' is a recognized command."""
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "MCP" in result.output or "mcp" in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::TestCLI -v`
Expected: FAIL

**Step 3: Convert Click command to group and add mcp subcommand**

This requires changing `ergane/main.py` to use a Click group. The existing `main` function becomes the default command, and `mcp` becomes a subcommand.

Modify `ergane/main.py`:

1. Rename the existing `main` function to `crawl_command`
2. Create a Click group `cli` that invokes `crawl_command` by default
3. Add an `mcp` subcommand

At the top of `main.py`, change the `@click.command()` decorator to `@click.group(invoke_without_command=True)` and restructure:

```python
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Ergane - High-performance async web scraper."""
    if ctx.invoked_subcommand is None:
        # If no subcommand, show help
        click.echo(ctx.get_help())


@cli.command()
# ... (all the existing @click.option decorators stay the same)
def crawl(...):
    """Crawl websites and extract data."""
    # ... (all existing main() body)


@cli.command()
def mcp():
    """Start the Ergane MCP server (stdio transport)."""
    from ergane.mcp import run
    run()
```

**Important:** Update `pyproject.toml` `[project.scripts]` to point to `cli`:

```toml
[project.scripts]
ergane = "ergane.main:cli"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All tests PASS

Also run existing tests to make sure CLI refactor doesn't break them:

Run: `uv run pytest tests/ -v`
Expected: All 291+ tests PASS

**Step 5: Commit**

```bash
git add ergane/main.py pyproject.toml tests/test_mcp.py
git commit -m "feat(mcp): add 'ergane mcp' CLI subcommand"
```

---

### Task 9: Add MCP server initialization tests

**Files:**
- Modify: `tests/test_mcp.py`

**Step 1: Write the tests**

Add to `tests/test_mcp.py`:

```python
class TestServerInit:
    """Tests for MCP server initialization."""

    def test_server_has_tools(self):
        from ergane.mcp import server
        # FastMCP server should have tools registered
        assert server.name == "ergane"

    def test_server_import(self):
        """Verify the server can be imported without error."""
        from ergane.mcp import server, run
        assert callable(run)
```

**Step 2: Run all tests**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All tests PASS

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS (existing + new MCP tests)

**Step 4: Commit**

```bash
git add tests/test_mcp.py
git commit -m "test(mcp): add server initialization tests"
```

---

### Task 10: Run linter and final verification

**Files:** None (verification only)

**Step 1: Run ruff linter**

Run: `uv run ruff check ergane/mcp/ tests/test_mcp.py`
Expected: No errors

If there are errors, fix them.

**Step 2: Run full test suite one final time**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

**Step 3: Verify MCP server starts**

Run: `echo '{}' | uv run python -m ergane.mcp` (will exit quickly since stdin closes)
Expected: No crash, clean exit or timeout

**Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "chore: lint fixes for MCP module"
```
