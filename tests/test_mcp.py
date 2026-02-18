"""Tests for the Ergane MCP server."""

import json

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
