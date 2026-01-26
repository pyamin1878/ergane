# Ergane

[![PyPI version](https://badge.fury.io/py/ergane.svg)](https://badge.fury.io/py/ergane)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

High-performance async web scraper with HTTP/2 support, built with Python.

*Named after Ergane, Athena's title as goddess of crafts and weaving in Greek mythology.*

## Features

- **HTTP/2 Support** - Fast concurrent connections via httpx
- **Rate Limiting** - Per-domain token bucket throttling
- **Retry Logic** - Exponential backoff (max 3 attempts)
- **robots.txt Compliance** - Respects crawler directives by default
- **Fast HTML Parsing** - Selectolax with CSS selector extraction (16x faster than BeautifulSoup)
- **Smart Scheduling** - Priority queue with URL deduplication
- **Multi-Format Output** - Export to CSV, Excel, or Parquet
- **Built-in Presets** - Pre-configured schemas for common sites (no coding required)
- **Graceful Shutdown** - Clean termination on SIGINT/SIGTERM
- **Custom Schemas** - Define Pydantic models with CSS selectors for type-safe extraction
- **Native Types** - Lists and nested objects stored as native Parquet types (not JSON strings)
- **Type Coercion** - Extract `"$19.99"` as `float(19.99)`, `"1,234"` as `int(1234)`
- **Proxy Support** - Route requests through HTTP/HTTPS proxies
- **Resume/Checkpoint** - Save and restore crawler state for long jobs
- **Structured Logging** - Configurable log levels and file output
- **Progress Bar** - Rich progress display with live stats
- **Config Files** - YAML configuration for persistent settings

## Installation

```bash
pip install ergane
```

For development:

```bash
pip install ergane[dev]
```

## Quick Start

### Using Presets (Easiest)

```bash
# Use a preset - no schema needed!
ergane --preset quotes -o quotes.csv

# Export to Excel
ergane --preset hacker-news -o stories.xlsx

# List available presets
ergane --list-presets
```

### Manual Crawling

```bash
# Crawl a single site
ergane -u https://example.com -n 100

# Crawl multiple start URLs
ergane -u https://site1.com -u https://site2.com -n 500

# Custom output and settings
ergane -u https://docs.python.org -n 50 -c 20 -r 5 -o python_docs.parquet
```

## Built-in Presets

Presets provide pre-configured schemas for popular websites:

| Preset | Site | Fields Extracted |
|--------|------|------------------|
| `hacker-news` | news.ycombinator.com | title, link, score, author, comments |
| `github-repos` | github.com/search | name, description, stars, language, link |
| `reddit` | old.reddit.com | title, subreddit, score, author, comments, link |
| `quotes` | quotes.toscrape.com | quote, author, tags |

```bash
# See all presets
ergane --list-presets

# Use preset with custom settings
ergane --preset hacker-news -n 100 -o hn.xlsx
```

## CLI Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--url` | `-u` | none | Start URL(s), can specify multiple |
| `--output` | `-o` | `output.parquet` | Output file path |
| `--max-pages` | `-n` | `100` | Maximum pages to crawl |
| `--max-depth` | `-d` | `3` | Maximum crawl depth from start URLs |
| `--concurrency` | `-c` | `10` | Concurrent requests |
| `--rate-limit` | `-r` | `10.0` | Requests per second per domain |
| `--timeout` | `-t` | `30.0` | Request timeout in seconds |
| `--same-domain` | | `true` | Stay on same domain as start URLs |
| `--any-domain` | | `false` | Follow links to any domain |
| `--ignore-robots` | | `false` | Ignore robots.txt restrictions |
| `--schema` | `-s` | none | YAML schema file for custom output fields |
| `--format` | `-f` | `auto` | Output format: `auto`, `csv`, `excel`, `parquet` |
| `--preset` | `-p` | none | Use a built-in preset |
| `--list-presets` | | | Show available presets and exit |
| `--proxy` | `-x` | none | HTTP/HTTPS proxy URL |
| `--resume` | | | Resume from last checkpoint |
| `--checkpoint-interval` | | `100` | Save checkpoint every N pages |
| `--log-level` | | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `--log-file` | | none | Write logs to file |
| `--no-progress` | | | Disable progress bar |
| `--config` | `-C` | none | Config file path |

## Custom Schemas

Define your own output schema with CSS selectors for type-safe extraction:

### Programmatic Usage

```python
from pydantic import BaseModel
from datetime import datetime
from ergane.schema import selector

class ProductItem(BaseModel):
    url: str                    # Auto-populated from crawled URL
    crawled_at: datetime        # Auto-populated timestamp

    name: str = selector("h1.product-title")
    price: float = selector("span.price", coerce=True)  # "$19.99" -> 19.99
    tags: list[str] = selector("span.tag")              # Native list type
    image_url: str = selector("img.product", attr="src")
    in_stock: bool = selector("span.availability")

# Use with Crawler
from ergane import Crawler, CrawlConfig

config = CrawlConfig(output_schema=ProductItem)
crawler = Crawler(
    config=config,
    start_urls=["https://example.com/products"],
    output_path="products.parquet",
    max_pages=100,
    max_depth=2,
    same_domain=True,
)
await crawler.run()
```

### YAML Schema (CLI)

Create a schema file `schema.yaml`:

```yaml
name: ProductItem
fields:
  name:
    selector: "h1.product-title"
    type: str
  price:
    selector: "span.price"
    type: float
    coerce: true
  tags:
    selector: "span.tag"
    type: list[str]
  image_url:
    selector: "img.product"
    attr: src
    type: str
```

Then run:

```bash
ergane -u https://example.com --schema schema.yaml -o products.parquet
```

### Type Coercion

The `coerce=true` option enables smart type conversion:

| Input | Target Type | Result |
|-------|-------------|--------|
| `"$19.99"` | `float` | `19.99` |
| `"1,234"` | `int` | `1234` |
| `"yes"` / `"true"` / `"1"` | `bool` | `True` |
| `"2024-01-15"` | `datetime` | `datetime(2024, 1, 15)` |

### Supported Types

| Python Type | Parquet Type | Example |
|-------------|--------------|---------|
| `str` | `Utf8` | `"Hello"` |
| `int` | `Int64` | `42` |
| `float` | `Float64` | `3.14` |
| `bool` | `Boolean` | `True` |
| `datetime` | `Datetime` | `datetime.now()` |
| `list[T]` | `List(T)` | `["a", "b"]` |
| `BaseModel` | `Struct` | Nested object |

## Output Formats

Ergane supports multiple output formats, auto-detected from file extension:

| Extension | Format | Best For |
|-----------|--------|----------|
| `.csv` | CSV | Universal compatibility, spreadsheets |
| `.xlsx` | Excel | Business users, non-technical stakeholders |
| `.parquet` | Parquet | Large datasets, data pipelines |

```bash
# Auto-detect from extension
ergane --preset quotes -o quotes.csv
ergane --preset quotes -o quotes.xlsx
ergane --preset quotes -o quotes.parquet

# Or explicitly specify format
ergane --preset quotes -o data.out --format csv
```

### Default Schema (without custom schema)

| Column | Type | Description |
|--------|------|-------------|
| `url` | string | Page URL |
| `title` | string | Page title |
| `text` | string | Extracted text content (max 10k chars) |
| `links` | string | JSON array of extracted links |
| `extracted_data` | string | JSON object of custom extractions |
| `crawled_at` | string | ISO timestamp |

### Reading Results

```python
import polars as pl

# Read any format
df = pl.read_parquet("output.parquet")
df = pl.read_csv("output.csv")
df = pl.read_excel("output.xlsx")

print(df.head())
```

## Benchmarks

Ergane uses selectolax for HTML parsing, which is significantly faster than BeautifulSoup:

| Operation         | Selectolax | BS4 + lxml | Speedup |
|-------------------|------------|------------|---------|
| Parse (small)     | 0.05ms     | 0.11ms     | 2.0x    |
| Parse (large)     | 0.19ms     | 6.05ms     | 31.1x   |
| Extract title     | 0.20ms     | 6.06ms     | 30.7x   |
| Extract links     | 0.25ms     | 6.73ms     | 27.3x   |
| Extract text      | 0.29ms     | 7.03ms     | 24.5x   |
| CSS selector      | 0.20ms     | 7.25ms     | 35.7x   |

**Average: 16x faster** (1000 iterations, 34KB HTML)

Run the benchmark:
```bash
pip install beautifulsoup4 lxml
python benchmarks/parse_benchmark.py
```

## Proxy Support

Route requests through a proxy server:

```bash
# HTTP proxy
ergane --preset quotes --proxy http://localhost:8080 -o quotes.csv

# Authenticated proxy
ergane -u https://example.com --proxy http://user:pass@proxy:8080 -o data.csv
```

## Resume/Checkpoint

For long-running crawls, Ergane automatically saves checkpoints:

```bash
# Start a large crawl
ergane --preset quotes -n 1000 -o large.csv
# Press Ctrl+C to interrupt

# Resume from checkpoint
ergane --preset quotes -n 1000 -o large.csv --resume

# Customize checkpoint interval (default: 100 pages)
ergane --preset quotes -n 1000 --checkpoint-interval 50 -o large.csv
```

Checkpoints are stored in `.ergane_checkpoint.json` and automatically deleted on successful completion.

## Config Files

Store persistent settings in a YAML config file:

```yaml
# ~/.ergane.yaml or ./.ergane.yaml
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

Ergane searches for config files in order:
1. `~/.ergane.yaml` (home directory)
2. `./.ergane.yaml` (current directory, hidden)
3. `./ergane.yaml` (current directory)

Or specify explicitly:
```bash
ergane --config myconfig.yaml --preset quotes -o quotes.csv
```

CLI arguments always override config file values.

## Logging

Control log output with `--log-level` and `--log-file`:

```bash
# Debug output
ergane --preset quotes --log-level DEBUG -o quotes.csv

# Save logs to file
ergane --preset quotes --log-level INFO --log-file crawl.log -o quotes.csv

# Disable progress bar (useful for scripts)
ergane --preset quotes --no-progress -o quotes.csv
```

## License

MIT
