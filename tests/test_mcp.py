"""Tests for the Ergane MCP server."""

import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ergane.mcp.prompts import (
    build_schema_prompt,
    choose_preset_prompt,
    plan_crawl_prompt,
)
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


class TestMCPJsParams:
    """Verify MCP tools accept js/js_wait parameters without error."""

    async def test_extract_tool_accepts_js_false(self, mock_server):
        """extract_tool works normally when js=False (default)."""
        result = await extract_tool(
            url=f"{mock_server}/",
            selectors={"title": "h1"},
            js=False,
        )
        data = json.loads(result)
        assert "title" in data

    async def test_crawl_tool_accepts_js_false(self, mock_server):
        """crawl_tool works normally when js=False (default)."""
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            max_pages=1,
            max_depth=0,
            js=False,
        )
        data = json.loads(result)
        assert isinstance(data, list)

    async def test_scrape_preset_tool_accepts_js_false(self):
        """scrape_preset_tool accepts js param.

        Invalid preset returns error with error_code.
        """
        result = await scrape_preset_tool(preset="nonexistent", js=False)
        data = json.loads(result)
        assert "error_code" in data


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
        assert "0.7.1" in result.output

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


# --- Step 1: Server Metadata + Tool Annotations ---


class TestServerMetadata:
    """Tests for MCP server instructions and website_url."""

    def test_server_has_instructions(self):
        from ergane.mcp import server
        assert server.instructions is not None
        assert "scraping" in server.instructions.lower()

    def test_server_has_website_url(self):
        from ergane.mcp import server
        assert server.website_url == "https://github.com/pyamin1878/ergane"


class TestToolAnnotations:
    """Tests for tool annotations and titles."""

    async def test_tools_have_titles(self):
        from ergane.mcp import server
        tools = await server.list_tools()
        tool_map = {t.name: t for t in tools}
        assert tool_map["list_presets_tool"].title == "List Presets"
        assert tool_map["extract_tool"].title == "Extract Page Data"
        assert tool_map["scrape_preset_tool"].title == "Scrape with Preset"
        assert tool_map["crawl_tool"].title == "Crawl Website"

    async def test_all_tools_readonly(self):
        from ergane.mcp import server
        tools = await server.list_tools()
        for tool in tools:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True

    async def test_list_presets_idempotent(self):
        from ergane.mcp import server
        tools = await server.list_tools()
        tool_map = {t.name: t for t in tools}
        lpt = tool_map["list_presets_tool"]
        assert lpt.annotations.idempotentHint is True
        assert lpt.annotations.openWorldHint is False


# --- Step 2: Exposed Params + Validation ---


class TestExposedParams:
    """Tests for newly exposed tool parameters."""

    async def test_extract_with_timeout(self, mock_server):
        result = await extract_tool(
            url=f"{mock_server}/", selectors={"title": "h1"}, timeout=30.0,
        )
        data = json.loads(result)
        assert data["title"] == "Home"

    async def test_extract_with_headers(self, mock_server):
        result = await extract_tool(
            url=f"{mock_server}/",
            selectors={"title": "h1"},
            headers={"X-Custom": "test"},
        )
        data = json.loads(result)
        assert "title" in data

    async def test_extract_invalid_timeout(self):
        result = await extract_tool(
            url="http://example.com/",
            selectors={"title": "h1"},
            timeout=0,
        )
        data = json.loads(result)
        assert data["error_code"] == "INVALID_PARAMS"

    async def test_crawl_with_rate_limit(self, mock_server):
        result = await crawl_tool(
            urls=[f"{mock_server}/"], max_pages=1, rate_limit=10.0,
        )
        data = json.loads(result)
        assert isinstance(data, (list, dict))

    async def test_crawl_with_ignore_robots(self, mock_server):
        result = await crawl_tool(
            urls=[f"{mock_server}/"], max_pages=1, ignore_robots=True,
        )
        data = json.loads(result)
        assert isinstance(data, (list, dict))

    async def test_crawl_with_same_domain_false(self, mock_server):
        result = await crawl_tool(
            urls=[f"{mock_server}/"], max_pages=1, same_domain=False,
        )
        data = json.loads(result)
        assert isinstance(data, (list, dict))

    async def test_crawl_with_headers(self, mock_server):
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            max_pages=1,
            headers={"Authorization": "Bearer test"},
        )
        data = json.loads(result)
        assert isinstance(data, (list, dict))

    async def test_crawl_invalid_rate_limit(self):
        result = await crawl_tool(
            urls=["http://example.com/"], max_pages=1, rate_limit=-1.0,
        )
        data = json.loads(result)
        assert data["error_code"] == "INVALID_PARAMS"

    async def test_crawl_invalid_concurrency(self):
        result = await crawl_tool(
            urls=["http://example.com/"], max_pages=1, concurrency=0,
        )
        data = json.loads(result)
        assert data["error_code"] == "INVALID_PARAMS"

    async def test_crawl_invalid_max_pages(self):
        result = await crawl_tool(urls=["http://example.com/"], max_pages=0)
        data = json.loads(result)
        assert data["error_code"] == "INVALID_PARAMS"

    async def test_scrape_preset_invalid_max_pages(self):
        result = await scrape_preset_tool(preset="quotes", max_pages=0)
        data = json.loads(result)
        assert data["error_code"] == "INVALID_PARAMS"


# --- Step 3: Progress Reporting + Logging ---


def _make_mock_context():
    """Create a mock MCP Context for testing."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.error = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.report_progress = AsyncMock()
    return ctx


class TestProgressReporting:
    """Tests for progress reporting and context logging."""

    async def test_crawl_reports_progress(self, mock_server):
        ctx = _make_mock_context()
        result = await crawl_tool(
            urls=[f"{mock_server}/"], max_pages=2, max_depth=1, ctx=ctx,
        )
        data = json.loads(result)
        assert isinstance(data, (list, dict))
        assert ctx.report_progress.call_count >= 1

    async def test_crawl_logs_completion(self, mock_server):
        ctx = _make_mock_context()
        await crawl_tool(
            urls=[f"{mock_server}/"], max_pages=1, ctx=ctx,
        )
        assert ctx.info.call_count >= 1

    async def test_extract_logs_info(self, mock_server):
        ctx = _make_mock_context()
        await extract_tool(
            url=f"{mock_server}/", selectors={"title": "h1"}, ctx=ctx,
        )
        # Should have called info at least twice (fetch + extraction)
        assert ctx.info.call_count >= 2

    async def test_extract_logs_warning_on_fetch_error(self):
        ctx = _make_mock_context()
        await extract_tool(
            url="http://localhost:1/nonexistent",
            selectors={"title": "h1"},
            ctx=ctx,
        )
        assert ctx.warning.call_count >= 1

    async def test_tools_work_without_context(self, mock_server):
        """Verify tools still work when ctx is None (direct calls)."""
        result = await crawl_tool(
            urls=[f"{mock_server}/"], max_pages=1,
        )
        data = json.loads(result)
        assert isinstance(data, (list, dict))


# --- Step 4: MCP Prompts ---


class TestPrompts:
    """Tests for MCP prompt templates."""

    def test_build_schema_returns_messages(self):
        result = build_schema_prompt(url="https://example.com")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert "example.com" in result[0].content.text

    def test_choose_preset_returns_messages(self):
        result = choose_preset_prompt(task="scrape news headlines")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert "hacker-news" in result[1].content.text

    def test_plan_crawl_returns_messages(self):
        result = plan_crawl_prompt(
            url="https://example.com", goal="collect product prices",
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert "max_pages" in result[1].content.text

    async def test_prompts_registered_on_server(self):
        from ergane.mcp import server
        prompts = await server.list_prompts()
        prompt_names = {p.name for p in prompts}
        assert "build-schema" in prompt_names
        assert "choose-preset" in prompt_names
        assert "plan-crawl" in prompt_names

    async def test_build_schema_has_url_argument(self):
        from ergane.mcp import server
        prompts = await server.list_prompts()
        build = next(p for p in prompts if p.name == "build-schema")
        assert build.arguments is not None
        arg_names = [a.name for a in build.arguments]
        assert "url" in arg_names

    async def test_choose_preset_has_task_argument(self):
        from ergane.mcp import server
        prompts = await server.list_prompts()
        choose = next(p for p in prompts if p.name == "choose-preset")
        assert choose.arguments is not None
        arg_names = [a.name for a in choose.arguments]
        assert "task" in arg_names


class TestCrawlProgress:
    """MCP crawl tool emits progress during execution."""

    async def test_crawl_reports_progress(self, mock_server):
        """crawl_tool calls ctx.report_progress at least once during a crawl."""
        import json
        from unittest.mock import AsyncMock, MagicMock

        ctx = MagicMock()
        ctx.report_progress = AsyncMock()
        ctx.info = AsyncMock()
        ctx.warning = AsyncMock()

        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            max_pages=2,
            ctx=ctx,
            same_domain=False,
            ignore_robots=True,
        )

        data = json.loads(result)
        assert isinstance(data, list)
        ctx.report_progress.assert_called()
