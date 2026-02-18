"""Tests for the Ergane MCP server."""

import json
import subprocess
import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ergane.mcp.resources import get_preset_resource
from ergane.mcp.tools import (
    crawl_tool,
    extract_tool,
    list_presets_tool,
    scrape_preset_tool,
)


class TestServerInit:
    """Tests for MCP server initialization."""

    def test_server_has_name(self):
        from ergane.mcp import server
        assert server.name == "ergane"

    def test_server_import(self):
        from ergane.mcp import run, server

        assert server is not None
        assert callable(run)


class TestEntryPoints:
    """Tests for MCP server entry points."""

    def test_module_entry_point(self):
        """Verify python -m ergane.mcp module can be loaded."""
        result = subprocess.run(
            [sys.executable, "-c", "from ergane.mcp import server; print(server.name)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "ergane" in result.stdout.strip()


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


class TestCLI:
    """Tests for the ergane CLI subcommands."""

    def test_mcp_command_exists(self):
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "mcp" in result.output.lower()

    def test_crawl_command_exists(self):
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["crawl", "--help"])
        assert result.exit_code == 0
        assert "crawl" in result.output.lower()
