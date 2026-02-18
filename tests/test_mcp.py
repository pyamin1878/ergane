"""Tests for the Ergane MCP server."""

import json

import pytest

from ergane.mcp.resources import get_preset_resource
from ergane.mcp.tools import extract_tool, list_presets_tool


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
