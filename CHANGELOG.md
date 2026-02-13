# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-02-13

### Added

- **Programmatic API**: Ergane is now usable as a Python library, not just a CLI tool
  - `Crawler` class with async context manager support
  - `run()` returns results as a list; `stream()` yields items incrementally
  - `crawl()` one-shot convenience function
  - Works without output path for pure in-memory usage
  ```python
  from ergane import Crawler, crawl

  # Context manager
  async with Crawler(urls=["https://example.com"], max_pages=10) as c:
      results = await c.run()

  # One-shot
  results = await crawl(urls=["https://example.com"], max_pages=10)
  ```

- **Hook System**: Intercept and modify requests/responses during crawling
  - `CrawlHook` protocol (structural subtyping — no inheritance required)
  - `BaseHook` convenience class (override only what you need)
  - Built-in hooks: `LoggingHook`, `AuthHeaderHook`, `StatusFilterHook`
  - Return `None` from a hook to skip a request or discard a response
  ```python
  from ergane import Crawler, BaseHook

  class MyHook(BaseHook):
      async def on_request(self, req):
          print(f"Fetching: {req.url}")
          return req

  async with Crawler(urls=[...], hooks=[MyHook()]) as c:
      await c.run()
  ```

- **New exports**: `Crawler`, `crawl`, `BaseHook`, `CrawlHook` added to `ergane.__init__`

### Fixed

- **User-agent string**: Changed from `Arachne/0.1` (wrong project) to `Ergane/0.6.0 (+https://github.com/pyamin1878/ergane)`
- **Default concurrency mismatch**: `CrawlConfig.max_concurrent_requests` default changed from `50` to `10` to match CLI behavior
- **Silent failures**: Added logging for robots.txt fetch failures (DEBUG), queue-full URL drops (WARNING), and empty content responses (WARNING)
- **Fragile tests**: Replaced `httpbin.org` calls in `test_fetcher.py` with local mock server

### Changed

- **BREAKING**: `Crawler` constructor now uses flat keyword args instead of `CrawlConfig` + scattered params
  - Old: `Crawler(config=config, start_urls=[...], output_path="out.parquet", max_pages=100, ...)`
  - New: `Crawler(urls=[...], output="out.parquet", max_pages=100, ...)`
- `ergane/main.py` reduced from 602 to ~250 lines (thin CLI wrapper over `engine.Crawler`)
- Fetcher now supports `request.metadata["headers"]` for injecting custom headers per-request
- Version is now defined in `ergane/_version.py` (single source of truth)

### Architecture

- New `ergane/crawler/engine.py`: Pure async crawl orchestration (no Click, Rich, or signal handling)
- New `ergane/crawler/hooks.py`: Hook protocol and built-in implementations
- Shared `MockHandler` in `tests/conftest.py` with `/get`, `/delay/{n}`, `/status/{code}` endpoints

## [0.3.1] - 2026-01-26

### Added

- **Proxy Support**: Route requests through HTTP/HTTPS proxies
  - New `--proxy/-x` CLI option for proxy URL
  - Supports authentication via URL (e.g., `http://user:pass@proxy:8080`)

- **Resume/Checkpoint**: Save and restore crawler state for long-running jobs
  - Automatic checkpoint saving every N pages (configurable via `--checkpoint-interval`)
  - Resume interrupted crawls with `--resume` flag
  - Checkpoint stored in `.ergane_checkpoint.json`

- **Structured Logging**: Replaced `click.echo` with Python logging
  - Configurable log levels via `--log-level` (DEBUG, INFO, WARNING, ERROR)
  - Optional file logging via `--log-file`
  - Timestamps and log levels in output

- **Progress Bar**: Rich progress display during crawling
  - Spinner, progress bar, and current URL display
  - Disable with `--no-progress` flag
  - New dependency: `rich>=13.0.0`

- **Config File Support**: Load settings from YAML config files
  - Automatic search in `~/.ergane.yaml`, `./.ergane.yaml`, `./ergane.yaml`
  - Explicit path via `--config/-C` option
  - CLI args override config file values

### New CLI Options

| Option | Short | Description |
|--------|-------|-------------|
| `--proxy` | `-x` | HTTP/HTTPS proxy URL |
| `--resume` | | Resume from last checkpoint |
| `--checkpoint-interval` | | Save checkpoint every N pages (default: 100) |
| `--log-level` | | DEBUG, INFO, WARNING, ERROR (default: INFO) |
| `--log-file` | | Write logs to file |
| `--no-progress` | | Disable progress bar |
| `--config` | `-C` | Config file path |

### Config File Format

```yaml
# ~/.ergane.yaml
crawler:
  rate_limit: 10.0
  concurrency: 20
  timeout: 30.0
  respect_robots_txt: true
  user_agent: "MyBot/1.0"
  proxy: null

defaults:
  max_pages: 100
  max_depth: 3
  same_domain: true
  output_format: parquet

logging:
  level: INFO
  file: null
```

## [0.3.0] - 2026-01-25

### Added

- **Multi-Format Output**: Export data to CSV, Excel (.xlsx), or Parquet formats
  - Auto-detection from file extension (`.csv`, `.xlsx`, `.parquet`)
  - Explicit format selection via `--format` CLI option
  - New dependencies: `xlsxwriter` and `fastexcel` for Excel support

- **Preset System**: Built-in presets for common websites
  - `hacker-news`: Hacker News front page stories
  - `github-repos`: GitHub repository search results
  - `reddit`: Reddit posts from old.reddit.com
  - `quotes`: quotes.toscrape.com (demo/testing site)
  - Each preset includes pre-configured schema and sensible defaults
  - Use `--list-presets` to see available options

- **Simplified CLI**: New options for easier usage
  - `--preset/-p`: Use a built-in preset (no schema writing needed)
  - `--list-presets`: Show available presets
  - `--format/-f`: Explicitly set output format

### Example Usage

```bash
# Use a preset - no schema needed!
ergane --preset quotes -o quotes.csv

# Export to Excel
ergane --preset hacker-news -o stories.xlsx

# List available presets
ergane --list-presets

# Preset with custom options
ergane --preset hacker-news -n 100 -o hn_stories.csv
```

## [0.2.0] - 2026-01-25

### Added

- **Custom Output Schemas**: Define Pydantic models with CSS selector mappings for type-safe extraction
- **Native Parquet Types**: Lists and structs stored as native Polars types instead of JSON strings
- **YAML Schema Support**: Load schemas from YAML files via `--schema` CLI option
- **Type Coercion**: Smart conversion of extracted strings to int, float, bool, datetime
  - Price extraction: `"$19.99"` -> `float(19.99)`
  - Number formatting: `"1,234"` -> `int(1234)`
  - Boolean values: `"yes"/"true"/"1"` -> `bool(True)`
- **Nested Model Support**: Extract complex hierarchical data with nested Pydantic models
- **Attribute Extraction**: Extract element attributes (href, src, data-*) via `attr` parameter

### New Modules

- `ergane/schema/` - Schema infrastructure for custom output types
  - `selector()` helper function for defining CSS selectors on Pydantic fields
  - `SchemaExtractor` for HTML to typed model extraction
  - `TypeCoercer` for string to typed value conversion
  - `ParquetSchemaMapper` for Pydantic to Polars schema mapping
  - `load_schema_from_yaml()` for YAML schema definitions

### Example Usage

```python
from pydantic import BaseModel
from datetime import datetime
from ergane.schema import selector

class ProductItem(BaseModel):
    url: str                    # Auto-populated
    crawled_at: datetime        # Auto-populated
    name: str = selector("h1.product-title")
    price: float = selector("span.price", coerce=True)
    tags: list[str] = selector("span.tag")
    image_url: str = selector("img.product", attr="src")
```

## [0.1.0] - 2025-01-24

### Added

- Initial release of Ergane web crawler
- Async HTTP/2 client using httpx for fast concurrent connections
- Per-domain rate limiting with token bucket algorithm
- Exponential backoff retry logic (max 3 attempts)
- robots.txt compliance (enabled by default)
- Fast HTML parsing with selectolax (16x faster than BeautifulSoup)
- Priority queue scheduler with URL deduplication
- Parquet output format via polars for efficient storage
- Graceful shutdown handling for SIGINT/SIGTERM
- CLI interface with configurable options:
  - Multiple start URLs support
  - Configurable concurrency and rate limits
  - Depth limiting
  - Same-domain or cross-domain crawling
  - Custom output paths
