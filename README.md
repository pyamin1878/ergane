# Arachne

High-performance async web scraper with HTTP/2 support, built with Python.

## Features

- **HTTP/2 Support** - Fast concurrent connections via httpx
- **Rate Limiting** - Per-domain token bucket throttling
- **Retry Logic** - Exponential backoff (max 3 attempts)
- **robots.txt Compliance** - Respects crawler directives by default
- **Fast HTML Parsing** - Selectolax with CSS selector extraction (16x faster than BeautifulSoup)
- **Smart Scheduling** - Priority queue with URL deduplication
- **Parquet Output** - Efficient columnar storage via polars
- **Graceful Shutdown** - Clean termination on SIGINT/SIGTERM

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Crawl a single site
arachne -u https://example.com -n 100

# Crawl multiple start URLs
arachne -u https://site1.com -u https://site2.com -n 500

# Custom output and settings
arachne -u https://docs.python.org -n 50 -c 20 -r 5 -o python_docs.parquet
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

Arachne uses selectolax for HTML parsing, which is significantly faster than BeautifulSoup:

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
