# Ergane

[![PyPI version](https://badge.fury.io/py/ergane.svg)](https://badge.fury.io/py/ergane)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

High-performance async web scraper with HTTP/2 support, built with Python.

*Named after Ergane, Athena's title as goddess of crafts and weaving in Greek mythology.*

## Features

- **HTTP/2 & Async** - Fast concurrent connections with rate limiting and retry logic
- **Fast Parsing** - Selectolax HTML parsing (16x faster than BeautifulSoup)
- **Built-in Presets** - Pre-configured schemas for popular sites (no coding required)
- **Custom Schemas** - Define Pydantic models with CSS selectors and type coercion
- **Multi-Format Output** - Export to CSV, Excel, Parquet, JSON, JSONL, or SQLite
- **Response Caching** - SQLite-based caching for faster development and debugging
- **Production Ready** - robots.txt compliance, graceful shutdown, checkpoints, proxy support

## Installation

```bash
pip install ergane
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

# Custom output and settings
ergane -u https://docs.python.org -n 50 -c 20 -r 5 -o python_docs.parquet
```

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

Ergane uses an async pipeline architecture orchestrated by a central **Crawler** engine. N worker coroutines run concurrently, each pulling URLs from the scheduler, fetching, parsing, and feeding results to the output pipeline.

```
  CLI args ──→ Config ←── YAML file          Presets / Custom Schema
               merge       (~/.ergane.yaml)       │
                 │                                 │
                 ▼                                 ▼
          ┌─────────────────────────────────────────────────────────────┐
          │                     Crawler  (engine)                       │
          │  Spawns N async workers · signal handling · progress bar    │
          │                                                             │
          │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ Worker loop (× N) ─ ─ ─ ─ ─ ─ ─ ┐  │
          │                                                             │
          │  │   ┌───────────────────────────────────────────────┐  │  │
          │      │              Scheduler                        │     │
          │  │   │  Min-heap priority queue · URL dedup (set)   │  │  │
          │      │  Depth limit · asyncio.Event signaling        │     │
          │  │   └──────────────┬────────────────────────────────┘  │  │
          │                     │ get_nowait() → CrawlRequest            │
          │  │                  ▼                                   │  │
          │      ┌──────────────────────────────────────────────┐     │
          │  │   │              Fetcher                          │  │  │
          │      │  httpx AsyncClient (HTTP/2) · proxy support  │     │
          │  │   │  Per-domain token-bucket rate limiter         │  │  │
          │      │  Exponential backoff retry · robots.txt      │     │
          │  │   └──────┬───────────────────────────────────────┘  │  │
          │             │ CrawlResponse                               │
          │  │          ▼                                           │  │
          │      ┌──────────────────────────────────────────────┐     │
          │  │   │              Parser                           │  │  │
          │      │  selectolax HTML parsing (16× BeautifulSoup) │     │
          │  │   │  Schema mode → typed Pydantic model          │  │  │
          │      │  Legacy mode → ParsedItem                    │     │
          │  │   │  Link extraction ─────────────────────┐      │  │  │
          │      └──────┬───────────────────────────────┐│──────┘     │
          │  │          │ model instance                 ││ new URLs│  │
          │             ▼                               │▼            │
          │  │   ┌────────────────────┐        ┌────────────────┐  │  │
          │      │     Pipeline       │        │   Scheduler    │     │
          │  │   │  Buffer → batch    │        │   .add_many()  │  │  │
          │      │  files (numbered)  │        └────────────────┘     │
          │  │   └────────┬───────────┘                            │  │
          │               │                                           │
          │  └ ─ ─ ─ ─ ─ ┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
          │               │                                            │
          └───────────────┼────────────────────────────────────────────┘
                          │ flush on batch_size
                          ▼
          ┌──────────────────────────────────────────────────────────┐
          │                   Pipeline  (output)                     │
          │  Incremental batch files → consolidate & dedup by URL   │
          │  Parquet · CSV · Excel · JSON · JSONL · SQLite           │
          └──────────────────────────────┬───────────────────────────┘
                                         │
                                         ▼
                                   output.parquet

  ┌──────────────────────────────────────────────────────────────────┐
  │                      Cross-cutting concerns                      │
  │                                                                  │
  │  Checkpoint ─ periodic JSON snapshots of scheduler state &       │
  │               page count; enables --resume after interruption    │
  │                                                                  │
  │  Cache ───── optional SQLite response cache with TTL             │
  │               (SHA-256 URL keys · non-blocking async I/O)        │
  │                                                                  │
  │  Schema ──── YAML loader → dynamic Pydantic model creation       │
  │               type coercion ($19.99→19.99) · Parquet type mapping │
  └──────────────────────────────────────────────────────────────────┘
```

## CLI Options

Common options:

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
| `--cache` | | `false` | Enable response caching |
| `--cache-dir` | | `.ergane_cache` | Cache directory |
| `--cache-ttl` | | `3600` | Cache TTL in seconds |

Run `ergane --help` for all options including proxy, resume, logging, and config settings.

## Response Caching

Enable caching to speed up development and debugging workflows:

```bash
# First run - fetches from web, caches responses
ergane --preset quotes --cache -n 10 -o quotes.csv

# Second run - instant (served from cache)
ergane --preset quotes --cache -n 10 -o quotes.csv

# Custom cache settings
ergane --preset bbc-news --cache --cache-dir ./my_cache --cache-ttl 60 -o news.csv
```

Cache is stored in SQLite at `.ergane_cache/response_cache.db` by default.

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

## Advanced CLI Examples

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
