# Ergane MCP Server Design

**Date:** 2026-02-18
**Status:** Approved

## Overview

Add an MCP (Model Context Protocol) server to Ergane, allowing LLMs to crawl websites and extract structured data as part of conversations and automated workflows. The server exposes Ergane's full capabilities — crawling, single-page extraction, and built-in presets — through the standard MCP tool and resource interfaces.

## Approach

**Optional extra within the existing package.** The MCP module lives at `ergane/mcp/` and the MCP SDK is an optional dependency installed via `pip install ergane[mcp]`. This keeps the core package lightweight while making the MCP server easy to install.

**SDK:** Official Python MCP SDK (`mcp` package) using FastMCP.
**Transport:** stdio (standard for local MCP servers used by Claude Code, Claude Desktop, etc.).

## Architecture

### Module Structure

```
ergane/
├── mcp/
│   ├── __init__.py        # FastMCP server instance, entry point
│   ├── tools.py           # Tool definitions
│   ├── resources.py       # Resource definitions
│   └── __main__.py        # python -m ergane.mcp support
```

### Packaging

- Add `mcp = ["mcp[cli]>=1.0.0"]` to `[project.optional-dependencies]` in `pyproject.toml`
- Install: `pip install ergane[mcp]` or `uv pip install ergane[mcp]`
- If `mcp` is not installed, importing `ergane.mcp` raises a clear error message

### CLI Integration

- Add `ergane mcp` subcommand to the existing Click CLI in `main.py`
- Also supports `python -m ergane.mcp` for direct invocation
- Both run the FastMCP server with stdio transport

## MCP Tools

### `crawl`

Full website crawl with structured extraction.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `urls` | list[str] | required | Starting URLs to crawl |
| `schema_yaml` | str | None | YAML schema definition for extraction |
| `max_pages` | int | 10 | Maximum pages to crawl |
| `max_depth` | int | 1 | How deep to follow links |
| `concurrency` | int | 5 | Concurrent requests |
| `output_format` | str | "json" | Result format: "json", "csv", "jsonl" |

**Returns:** Extracted data as text. For large result sets, returns first 50 items with a total count.

### `extract`

Single-page extraction — fetch one URL and extract structured data.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | str | required | URL to scrape |
| `selectors` | dict[str, str] | None | Field name to CSS selector mapping |
| `schema_yaml` | str | None | Full YAML schema (alternative to selectors) |

**Returns:** Extracted data as JSON object. The "quick scrape" tool for LLMs.

### `scrape_preset`

Scrape using a built-in preset — zero configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `preset` | str | required | Preset name (e.g., "hacker_news") |
| `max_pages` | int | 5 | Maximum pages to scrape |

**Returns:** Extracted data as JSON array.

### `list_presets`

Discover available presets.

**Parameters:** None
**Returns:** JSON array of presets with name, description, target URL, and fields.

## MCP Resources

### `preset://{name}`

Each built-in preset is exposed as a browsable MCP resource. Reading a preset resource returns:

```json
{
  "name": "hacker_news",
  "description": "Hacker News front page stories",
  "url": "https://news.ycombinator.com",
  "fields": ["title", "url", "score", "author", "comments"]
}
```

The resource list enumerates all available presets so clients can discover them.

## Error Handling & Safety

- **Timeouts:** 60s default for `extract`, 300s for `crawl`. Progress updates via MCP context during long crawls.
- **Rate limiting:** Ergane's built-in rate limiting applies as-is.
- **Result truncation:** Large result sets truncated to first 50 items with total count included.
- **Robots.txt:** Ergane's existing compliance is respected.
- **Error responses:** Network errors, invalid URLs, and parse failures returned as structured error messages.

## Testing

- Unit tests for each tool function (mock the Ergane crawler)
- Integration test with mock HTTP server (reuse existing `conftest.py` fixtures)
- Test MCP server initialization and tool registration
- Test resource resolution
- Test error cases (invalid URLs, bad selectors, timeouts)

Tests in `tests/test_mcp.py`.
