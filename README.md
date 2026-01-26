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
- **Parquet Output** - Efficient columnar storage via polars
- **Graceful Shutdown** - Clean termination on SIGINT/SIGTERM
- **Custom Schemas** - Define Pydantic models with CSS selectors for type-safe extraction
- **Native Types** - Lists and nested objects stored as native Parquet types (not JSON strings)
- **Type Coercion** - Extract `"$19.99"` as `float(19.99)`, `"1,234"` as `int(1234)`

## Installation

```bash
pip install ergane
```

For development:

```bash
pip install ergane[dev]
```

## Quick Start

```bash
# Crawl a single site
ergane -u https://example.com -n 100

# Crawl multiple start URLs
ergane -u https://site1.com -u https://site2.com -n 500

# Custom output and settings
ergane -u https://docs.python.org -n 50 -c 20 -r 5 -o python_docs.parquet
```

## CLI Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--url` | `-u` | required | Start URL(s), can specify multiple |
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

## Output Format

Results are saved as a Parquet file with the following schema:

| Column | Type | Description |
|--------|------|-------------|
| `url` | string | Page URL |
| `title` | string | Page title |
| `text` | string | Extracted text content (max 10k chars) |
| `links` | string | JSON array of extracted links |
| `extracted_data` | string | JSON object of custom extractions |
| `crawled_at` | string | ISO timestamp |

Read results with polars:

```python
import polars as pl

df = pl.read_parquet("output.parquet")
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

## License

MIT
