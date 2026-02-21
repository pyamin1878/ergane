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


class TestCrawlToolOutputFormats:
    """Tests for CSV and JSONL output formats in crawl_tool."""

    async def test_crawl_csv_output(self, mock_server):
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            max_pages=1,
            max_depth=0,
            output_format="csv",
        )
        # Valid CSV should not start with '#' (that would break CSV parsers)
        assert not result.startswith("#")
        # Should have at least a header row
        lines = [ln for ln in result.strip().splitlines() if ln]
        assert len(lines) >= 1

    async def test_crawl_jsonl_output(self, mock_server):
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            max_pages=1,
            max_depth=0,
            output_format="jsonl",
        )
        lines = [ln for ln in result.strip().splitlines() if ln]
        # Each line must be valid JSON (no '//' comments)
        for line in lines:
            parsed = json.loads(line)
            assert isinstance(parsed, dict)

    async def test_crawl_csv_empty(self):
        result = await crawl_tool(
            urls=["http://localhost:1/nonexistent"],
            max_pages=1,
            output_format="csv",
        )
        # Empty crawl → empty string (no crash)
        assert isinstance(result, str)


class TestErrorCodes:
    """Tests for structured error_code in MCP error responses."""

    async def test_extract_fetch_error_has_code(self):
        result = await extract_tool(
            url="http://localhost:1/nonexistent",
            selectors={"title": "h1"},
        )
        data = json.loads(result)
        assert "error_code" in data
        assert data["error_code"] == "FETCH_ERROR"

    async def test_scrape_invalid_preset_has_code(self):
        result = await scrape_preset_tool(preset="nonexistent-preset")
        data = json.loads(result)
        assert "error_code" in data
        assert data["error_code"] == "INVALID_PRESET"

    async def test_extract_bad_schema_has_code(self, mock_server):
        result = await extract_tool(
            url=f"{mock_server}/",
            schema_yaml="this: is: not: valid: yaml: ::::",
        )
        data = json.loads(result)
        assert "error_code" in data
        assert data["error_code"] == "SCHEMA_ERROR"

    async def test_crawl_bad_schema_has_code(self, mock_server):
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            schema_yaml="this: is: not: valid: yaml: ::::",
            max_pages=1,
        )
        data = json.loads(result)
        assert "error_code" in data
        assert data["error_code"] == "SCHEMA_ERROR"


class TestTruncation:
    """Tests for result truncation metadata."""

    async def test_truncated_result_has_metadata(self, mock_server):
        """When results exceed MAX_RESULT_ITEMS the envelope includes total."""
        from ergane.mcp.tools import MAX_RESULT_ITEMS, _truncate_json

        # Build a list larger than the limit
        items = [{"i": i} for i in range(MAX_RESULT_ITEMS + 5)]
        result = json.loads(_truncate_json(items, MAX_RESULT_ITEMS))
        assert result["truncated"] is True
        assert result["total"] == MAX_RESULT_ITEMS + 5
        assert len(result["items"]) == MAX_RESULT_ITEMS

    async def test_non_truncated_result_is_plain_list(self, mock_server):
        from ergane.mcp.tools import MAX_RESULT_ITEMS, _truncate_json

        items = [{"i": i} for i in range(3)]
        result = json.loads(_truncate_json(items, MAX_RESULT_ITEMS))
        assert isinstance(result, list)
        assert len(result) == 3


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

    def test_version_flag(self):
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.7.0" in result.output

    def test_negative_max_pages_rejected(self, mock_server):
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["crawl", "-u", f"{mock_server}/", "--max-pages", "-1"],
        )
        assert result.exit_code != 0
        assert "max-pages" in result.output.lower() or "Error" in result.output

    def test_zero_concurrency_rejected(self, mock_server):
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["crawl", "-u", f"{mock_server}/", "--concurrency", "0"],
        )
        assert result.exit_code != 0

    def test_negative_rate_limit_rejected(self, mock_server):
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["crawl", "-u", f"{mock_server}/", "--rate-limit", "-5"],
        )
        assert result.exit_code != 0

    def test_negative_timeout_rejected(self, mock_server):
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["crawl", "-u", f"{mock_server}/", "--timeout", "0"],
        )
        assert result.exit_code != 0

    def test_js_flag_accepted(self):
        """--js flag appears in crawl --help output."""
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["crawl", "--help"])
        assert "--js" in result.output

    def test_js_wait_choices(self):
        """--js-wait rejects invalid strategies."""
        from ergane.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["crawl", "-u", "http://example.com", "--js-wait", "invalid"],
        )
        assert result.exit_code != 0
