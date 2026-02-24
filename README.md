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
- **Production Ready** — robots.txt compliance, graceful shutdown, checkpoints, proxy support

## Installation

```bash
pip install ergane

# With MCP server support (optional)
pip install ergane[mcp]
```

## Quick Start

### CLI — run from your terminal

```bash
# Use a built-in preset (no code needed)
ergane --preset quotes -o quotes.csv

# Crawl a custom URL
ergane -u https://example.com -n 100 -o data.parquet

# List available presets
ergane --list-presets
```

### Python — embed in your application

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

## Python Library

Ergane's engine is a pure async library. The CLI is a thin wrapper around it — everything the CLI can do, your code can do too.

### Crawler

The main entry point. Use it as an async context manager:

```python
from ergane import Crawler

async with Crawler(
    urls=["https://example.com"],
    max_pages=50,
    concurrency=10,
    rate_limit=5.0,
) as crawler:
    results = await crawler.run()      # collect all items
```

Key parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `urls` | *(required)* | Seed URL(s) to start crawling |
| `schema` | `None` | Pydantic model for typed extraction |
| `concurrency` | `10` | Number of concurrent workers |
| `max_pages` | `100` | Maximum pages to crawl |
| `max_depth` | `3` | Maximum link-follow depth |
| `rate_limit` | `10.0` | Requests per second per domain |
| `timeout` | `30.0` | HTTP request timeout (seconds) |
| `same_domain` | `True` | Only follow links on the seed domain |
| `hooks` | `None` | List of `CrawlHook` instances |
| `output` | `None` | File path to write results |
| `output_format` | `"auto"` | `csv`, `excel`, `parquet`, `json`, `jsonl`, `sqlite` |
| `cache` | `False` | Enable SQLite response caching |

### run()

Executes the crawl and returns all extracted items as a list:

```python
async with Crawler(urls=["https://example.com"], max_pages=10) as c:
    results = await c.run()
    print(f"Got {len(results)} items")
```

### stream()

Yields items as they arrive — memory-efficient for large crawls:

```python
async with Crawler(urls=["https://example.com"], max_pages=500) as c:
    async for item in c.stream():
        process(item)  # handle each item immediately
```

### crawl()

One-shot convenience function — creates a `Crawler`, runs it, returns results:

```python
from ergane import crawl

results = await crawl(
    urls=["https://example.com"],
    max_pages=10,
    concurrency=5,
)
```

### Typed Extraction with Schemas

Pass a Pydantic model with CSS selectors to extract structured data:

```python
from datetime import datetime
from pydantic import BaseModel
from ergane import Crawler, selector

class Quote(BaseModel):
    url: str
    crawled_at: datetime
    text: str = selector("span.text")
    author: str = selector("small.author")
    tags: list[str] = selector("div.tags a.tag")

async with Crawler(
    urls=["https://quotes.toscrape.com"],
    schema=Quote,
    max_pages=50,
) as crawler:
    for quote in await crawler.run():
        print(f"{quote.author}: {quote.text}")
```

The `selector()` helper supports:

| Argument | Description |
|----------|-------------|
| `css` | CSS selector string |
| `attr` | Extract an attribute instead of text (e.g. `"href"`, `"src"`) |
| `coerce` | Aggressive type coercion (`"$19.99"` → `19.99`) |
| `default` | Default value if selector matches nothing |

## Hooks

Hooks let you intercept and modify requests before they're sent, and responses after they're received. They follow the `CrawlHook` protocol:

```python
from ergane import CrawlHook, CrawlRequest, CrawlResponse

class CrawlHook(Protocol):
    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None: ...
    async def on_response(self, response: CrawlResponse) -> CrawlResponse | None: ...
```

Return the (possibly modified) object to continue, or `None` to skip/discard.

### BaseHook

Subclass `BaseHook` and override only the methods you need:

```python
from ergane import BaseHook, CrawlRequest

class SkipAdminPages(BaseHook):
    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None:
        if "/admin" in request.url:
            return None  # skip this URL
        return request
```

### Built-in Hooks

| Hook | Purpose |
|------|---------|
| `LoggingHook()` | Logs requests and responses at DEBUG level |
| `AuthHeaderHook(headers)` | Injects custom headers (e.g. `{"Authorization": "Bearer ..."}`) |
| `StatusFilterHook(allowed)` | Discards responses outside allowed status codes (default: `{200}`) |

### Using Hooks

```python
from ergane import Crawler
from ergane.crawler.hooks import LoggingHook, AuthHeaderHook

async with Crawler(
    urls=["https://api.example.com"],
    hooks=[
        AuthHeaderHook({"Authorization": "Bearer token123"}),
        LoggingHook(),
    ],
) as crawler:
    results = await crawler.run()
```

Hooks run in order: for requests, each hook receives the output of the previous one. The same applies for responses.

## MCP Server

Ergane includes an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that lets LLMs crawl websites and extract structured data. Install the optional dependency:

```bash
pip install ergane[mcp]
```

### Running the Server

```bash
# Via CLI subcommand
ergane mcp

# Via Python module
python -m ergane.mcp
```

Both start a stdio-based MCP server compatible with Claude Code, Claude Desktop, and other MCP clients.

### Configuration

Add to your MCP client config (e.g. Claude Desktop `claude_desktop_config.json`):

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

Or for Claude Code (`~/.claude/claude_code_config.json`):

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

### Available Tools

The MCP server exposes four tools:

#### `list_presets_tool`

Discover all built-in scraping presets with their target URLs and available fields.

#### `extract_tool`

Extract structured data from a single web page using CSS selectors.

```
Arguments:
  url          — URL to scrape (required)
  selectors    — Map of field names to CSS selectors, e.g. {"title": "h1", "price": ".price"}
  schema_yaml  — Full YAML schema (alternative to selectors)
```

#### `scrape_preset_tool`

Scrape a website using a built-in preset — zero configuration needed.

```
Arguments:
  preset     — Preset name, e.g. "hacker-news", "quotes" (required)
  max_pages  — Maximum pages to scrape (default: 5)
```

#### `crawl_tool`

Crawl one or more websites with full control over depth, concurrency, and output format.

```
Arguments:
  urls           — Starting URLs (required)
  schema_yaml    — YAML schema for CSS-based extraction
  max_pages      — Maximum pages to crawl (default: 10)
  max_depth      — Link-follow depth (default: 1, 0 = seed only)
  concurrency    — Concurrent requests (default: 5)
  output_format  — "json", "csv", or "jsonl" (default: "json")
```

### Resources

Each built-in preset is also exposed as an MCP resource at `preset://{name}` (e.g. `preset://hacker-news`), allowing LLMs to browse preset details before scraping.

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

## Custom Schemas

Define extraction rules in a YAML schema file:

```yaml
# schema.yaml
name: ProductItem
fields:
  name:
    selector: "h1.product-title"
    type: str
  price:
    selector: "span.price"
    type: float
    coerce: true  # "$19.99" -> 19.99
  tags:
    selector: "span.tag"
    type: list[str]
  image_url:
    selector: "img.product"
    attr: src
    type: str
```

```bash
ergane -u https://example.com --schema schema.yaml -o products.parquet
```

Type coercion (`coerce: true`) handles common patterns: `"$19.99"` → `19.99`, `"1,234"` → `1234`, `"yes"` → `True`.

Supported types: `str`, `int`, `float`, `bool`, `datetime`, `list[T]`.

You can also load YAML schemas programmatically:

```python
from ergane import Crawler, load_schema_from_yaml

ProductItem = load_schema_from_yaml("schema.yaml")

async with Crawler(
    urls=["https://example.com"],
    schema=ProductItem,
) as crawler:
    results = await crawler.run()
```

## Output Formats

Output format is auto-detected from file extension:

```bash
ergane --preset quotes -o quotes.csv      # CSV
ergane --preset quotes -o quotes.xlsx     # Excel
ergane --preset quotes -o quotes.parquet  # Parquet (default)
ergane --preset quotes -o quotes.json     # JSON array
ergane --preset quotes -o quotes.jsonl    # JSONL (one object per line)
ergane --preset quotes -o quotes.sqlite   # SQLite database
```

You can also force a format with `--format`/`-f` regardless of file extension:

```bash
ergane --preset quotes -f jsonl -o output.dat
```

```python
import polars as pl
df = pl.read_parquet("output.parquet")
```

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

### Internal design notes

**Config** — CLI flags and YAML config file are merged once into a `CrawlOptions` dataclass (in `ergane/config.py`) before any crawl work begins. All defaults live in one place; the config file sets the baseline and CLI flags override.

**Schema pipeline** — YAML schemas are parsed directly into `FieldConfig` objects (selector, type, coerce, attr) which drive extraction and serialisation. Programmatic schemas defined with `selector()` on Pydantic models follow the same `FieldConfig` representation via `SchemaConfig.from_model()`.

**Pipeline writers** — Each output format is handled by a dedicated `BatchWriter` subclass (`ParquetWriter`, `CsvWriter`, `ExcelWriter`, `JsonWriter`, `JsonlWriter`, `SqliteWriter`). Adding a new format means adding one class; the core `Pipeline` batching and consolidation logic is untouched.

## CLI Reference

### Common Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--url` | `-u` | none | Start URL(s), can specify multiple |
| `--output` | `-o` | `output.parquet` | Output file path |
| `--max-pages` | `-n` | `100` | Maximum pages to crawl |
| `--max-depth` | `-d` | `3` | Maximum crawl depth |
| `--concurrency` | `-c` | `10` | Concurrent requests |
| `--rate-limit` | `-r` | `10.0` | Requests per second per domain |
| `--schema` | `-s` | none | YAML schema file for custom extraction |
| `--preset` | `-p` | none | Use a built-in preset |
| `--format` | `-f` | `auto` | Output format: `csv`, `excel`, `parquet`, `json`, `jsonl`, `sqlite` |
| `--timeout` | `-t` | `30` | Request timeout in seconds |
| `--proxy` | `-x` | none | HTTP/HTTPS proxy URL |
| `--same-domain/--any-domain` | | `--same-domain` | Restrict crawling to seed domain |
| `--ignore-robots` | | `false` | Ignore robots.txt |
| `--cache` | | `false` | Enable response caching |
| `--cache-dir` | | `.ergane_cache` | Cache directory |
| `--cache-ttl` | | `3600` | Cache TTL in seconds |
| `--resume` | | | Resume from checkpoint |
| `--checkpoint-interval` | | `100` | Save checkpoint every N pages |
| `--log-level` | | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--log-file` | | none | Write logs to file |
| `--no-progress` | | | Disable progress bar |
| `--config` | `-C` | none | Config file path |

Run `ergane --help` for the full list.

### Advanced CLI Examples

```bash
# Crawl with a proxy
ergane -u https://example.com -o data.csv --proxy http://localhost:8080

# Resume an interrupted crawl (requires prior checkpoint)
ergane -u https://example.com -n 500 --resume

# Save checkpoints every 50 pages with debug logging
ergane -u https://example.com -n 500 --checkpoint-interval 50 \
    --log-level DEBUG --log-file crawl.log

# Use a YAML config file and override concurrency from CLI
ergane -u https://example.com -C config.yaml -c 20

# Combine preset with custom URL and explicit format
ergane --preset hacker-news -u https://news.ycombinator.com/newest \
    -f csv -o newest.csv -n 200
```

## Configuration

Ergane looks for a config file in these locations (first match wins):

1. Explicit path via `--config`/`-C`
2. `~/.ergane.yaml`
3. `./.ergane.yaml`
4. `./ergane.yaml`

```yaml
crawler:
  max_pages: 100
  max_depth: 3
  concurrency: 10
  rate_limit: 10.0

defaults:
  output_format: "csv"
  checkpoint_interval: 100

logging:
  level: "INFO"
  file: null
```

CLI flags override config file values.

## Troubleshooting

### Getting empty or partial output

- **Check `--max-depth`**: depth 0 means only the seed URL is crawled.
  Increase with `-d 3` to follow links.
- **Same-domain filtering**: by default Ergane only follows links on the
  same domain as the seed URL. Use `--any-domain` to crawl cross-domain.
- **Selector mismatch**: if using a custom schema, verify your CSS
  selectors match the actual site HTML (sites change frequently).

### Blocked by robots.txt

If a target site disallows your user-agent in `robots.txt`, Ergane will
return 403 for those URLs. Options:

```bash
# Ignore robots.txt (use responsibly)
ergane -u https://example.com --ignore-robots -o data.csv
```

### Rate limiting or 429 responses

Lower the request rate and concurrency:

```bash
ergane -u https://example.com -r 2 -c 3 -o data.csv
```

The built-in per-domain token-bucket rate limiter (`-r`) controls requests
per second. Reducing concurrency (`-c`) also lowers overall load.

### Timeouts and connection errors

Increase the request timeout and enable retries (3 retries is the default):

```bash
ergane -u https://slow-site.com -t 60 -o data.csv
```

### Resuming after a crash

Ergane periodically saves checkpoints (default: every 100 pages). To
resume:

```bash
ergane -u https://example.com -n 1000 --resume
```

The checkpoint file is automatically deleted after a successful crawl.

## License

MIT
