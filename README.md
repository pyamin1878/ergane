# Ergane

[![PyPI version](https://badge.fury.io/py/ergane.svg)](https://badge.fury.io/py/ergane)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

High-performance async web scraper with HTTP/2 support, built with Python.

*Named after Ergane, Athena's title as goddess of crafts and weaving in Greek mythology.*

## Features

- **Programmatic API** — `Crawler`, `crawl()`, and `stream()` let you embed scraping in any Python application
- **Hook System** — Intercept requests and responses with the `CrawlHook` protocol
- **HTTP/2 & Async** — Fast concurrent connections with per-domain rate limiting and retry logic
- **Fast Parsing** — Selectolax HTML parsing (16x faster than BeautifulSoup)
- **Built-in Presets** — Pre-configured schemas for popular sites (no coding required)
- **Custom Schemas** — Define Pydantic models with CSS selectors and type coercion
- **Multi-Format Output** — Export to CSV, Excel, Parquet, JSON, JSONL, or SQLite
- **Response Caching** — SQLite-based caching for faster development and debugging
- **MCP Server** — Expose scraping tools to LLMs via the Model Context Protocol
- **JavaScript Rendering** — Render JS-heavy pages via Playwright
- **Production Ready** — robots.txt compliance, graceful shutdown, checkpoints, proxy support

## Installation

```bash
pip install ergane

# With JavaScript rendering support
pip install ergane[js]

# With MCP server support
pip install ergane[mcp]
```

## Quick Start

### CLI

```bash
# Use a built-in preset (no code needed)
ergane --preset quotes -o quotes.csv

# Crawl a custom URL
ergane -u https://example.com -n 100 -o data.parquet

# List available presets
ergane --list-presets
```

### Python

```python
import asyncio
from ergane import Crawler

async def main():
    async with Crawler(
        urls=["https://quotes.toscrape.com"],
        max_pages=20,
    ) as crawler:
        async for item in crawler.stream():
            print(item.url, item.title)

asyncio.run(main())
```

### MCP Server

```bash
pip install ergane[mcp]
ergane mcp
```

Add to your Claude Desktop or Claude Code config:

```json
{
  "mcpServers": {
    "ergane": {
      "command": "ergane",
      "args": ["mcp"]
    }
  }
}
```

The server exposes four tools: `list_presets_tool`, `extract_tool`, `scrape_preset_tool`, and `crawl_tool`.

## Documentation

| Guide | Description |
|-------|-------------|
| [CLI Reference](docs/cli.md) | Commands, flags, presets, schemas, config files, troubleshooting |
| [Python Library](docs/python-library.md) | Crawler API, hooks, typed extraction, authentication, advanced usage |
| [MCP Server](docs/mcp-server.md) | Setup, tool reference, error handling, result format |

## Built-in Presets

| Preset | Site | Fields Extracted |
|--------|------|------------------|
| `hacker-news` | news.ycombinator.com | title, link, score, author, comments |
| `github-repos` | github.com/search | name, description, stars, language, link |
| `reddit` | old.reddit.com | title, subreddit, score, author, comments, link |
| `quotes` | quotes.toscrape.com | quote, author, tags |
| `amazon-products` | amazon.com | title, price, rating, reviews, link |
| `ebay-listings` | ebay.com | title, price, condition, shipping, link |
| `wikipedia-articles` | en.wikipedia.org | title, link |
| `bbc-news` | bbc.com/news | title, summary, link |

## Architecture

Ergane separates the **engine** (pure async library) from its three interfaces: the **CLI** (Rich progress bars, signal handling), the **Python library** (direct import), and the **MCP server** (LLM integration). Hooks plug into the pipeline at two points: after scheduling and after fetching.

```
         CLI (main.py)              Python Library             MCP Server
    ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
    │  Click options        │  │  from ergane import   │  │  FastMCP (stdio)     │
    │  Rich progress bar    │  │  Crawler / crawl()    │  │  4 tools + resources │
    │  Signal handling      │  │  stream()             │  │  ergane mcp          │
    │  CrawlOptions config  │  │                       │  │                      │
    └──────────┬───────────┘  └────────────┬──────────┘  └──────────┬───────────┘
               │                           │                        │
               └───────────────┬───────────┴────────────────────────┘
                              │
                              ▼
               ┌──────────────────────────────────┐
               │         Crawler  (engine)         │
               │    Pure async · no I/O concerns   │
               │    Spawns N worker coroutines     │
               └──────────────┬───────────────────┘
                              │
              ┌───────────────┼───────────────────┐
              │               │                   │
              ▼               ▼                   ▼
      ┌──────────────┐ ┌───────────┐   ┌──────────────────────┐
      │  Scheduler   │ │  Fetcher  │   │   Pipeline           │
      │  URL frontier│ │  HTTP/2   │   │  BatchWriter strategy│
      │  dedup queue │ │  retries  │   │  per-format writers  │
      └──────┬───────┘ └─────┬─────┘   └──────────────────────┘
             │               │
             ▼               ▼
  ┌──────────────────────────────────────────────────┐
  │                Worker loop (× N)                  │
  │                                                   │
  │  1. Scheduler.get()   → CrawlRequest              │
  │  2. hooks.on_request  → modify / skip             │
  │  3. Fetcher.fetch()   → CrawlResponse             │
  │  4. hooks.on_response → modify / discard          │
  │  5. Parser.extract()  → Pydantic model / dict     │
  │  6. Pipeline.add()    → buffered output           │
  │  7. extract_links()   → new URLs → Scheduler      │
  └──────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────┐
  │               Cross-cutting concerns              │
  │                                                   │
  │  Cache ─── SQLite response cache with TTL         │
  │  Checkpoint ─ periodic JSON snapshots for resume  │
  │  Schema ── YAML → FieldConfig → extraction        │
  └──────────────────────────────────────────────────┘
```

## License

MIT
