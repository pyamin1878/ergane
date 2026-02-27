# Ergane CLI Reference

Complete command-line reference for the Ergane web scraper.

---

## Quick Start

```bash
# Install ergane
pip install ergane

# Scrape Hacker News front page using a built-in preset
ergane --preset hacker-news -o stories.csv

# Crawl a site with a custom schema
ergane -u https://example.com -s schema.yaml -o data.json -n 50
```

---

## Commands

Ergane provides four commands. `crawl` is the default and is implied when omitted.

### `crawl` (default)

Crawl one or more URLs and extract structured data.

```bash
# Explicit
ergane crawl -u https://example.com -o output.csv

# Implicit — crawl is assumed when you pass options directly
ergane -u https://example.com -o output.csv
```

Only `--version` and `--help` are handled at the top level; every other invocation
is routed to `crawl`.

### `test-schema`

Test a YAML schema against a single page without running a full crawl. Both
`--url`/`-u` and `--schema`/`-s` are required. Fetches the URL, runs each CSS
selector, and prints a Rich table showing each field's extracted value or
`MISSING`.

```bash
ergane test-schema -u https://quotes.toscrape.com -s quotes.yaml
```

### `mcp`

Start the MCP (Model Context Protocol) server using stdio transport. No
additional options are accepted. See [mcp-server.md](mcp-server.md) for
protocol details.

```bash
ergane mcp
```

### `auth`

Manage authentication sessions. Three subcommands are available:

```bash
# Run the login flow and save the session without crawling
ergane auth login [--config-file PATH] [--auth-mode auto|manual]

# Check whether a saved session file exists
ergane auth status [--session-file FILE]

# Delete the saved session file
ergane auth clear [--session-file FILE]
```

The default session file is `.ergane_session.json`.

---

## Common Options

All options for the `crawl` command:

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--url` | `-u` | TEXT (multiple) | none | Start URL(s) to crawl. Repeat for multiple. |
| `--output` | `-o` | TEXT | `output.parquet` | Output file path (.parquet, .csv, .xlsx, .json, .jsonl, .sqlite) |
| `--max-pages` | `-n` | INT | `100` | Maximum pages to crawl |
| `--max-depth` | `-d` | INT | `3` | Maximum link-follow depth. 0 = seed URLs only. |
| `--concurrency` | `-c` | INT | `10` | Concurrent requests |
| `--rate-limit` | `-r` | FLOAT | `10.0` | Max requests per second per domain |
| `--timeout` | `-t` | FLOAT | `30.0` | Request timeout in seconds |
| `--same-domain/--any-domain` | | FLAG | `--same-domain` | Restrict to same domain (default) or allow cross-domain |
| `--ignore-robots` | | FLAG | `false` | Ignore robots.txt restrictions |
| `--schema` | `-s` | PATH | none | YAML schema file for custom output fields |
| `--format` | `-f` | CHOICE | `auto` | Output format: auto, csv, excel, parquet, json, jsonl, sqlite |
| `--preset` | `-p` | TEXT | none | Use a built-in preset |
| `--list-presets` | | FLAG | | Show available presets and exit |
| `--proxy` | `-x` | TEXT | none | HTTP/HTTPS proxy URL (e.g., `http://localhost:8080`) |
| `--domain-rate-limit` | | TEXT (multiple) | none | Per-domain rate limit as `DOMAIN:RATE`. Overrides `--rate-limit` for that domain. Repeat for multiple domains. |
| `--resume` | | FLAG | | Resume from last checkpoint |
| `--checkpoint-interval` | | INT | `100` | Save checkpoint every N pages |
| `--log-level` | | CHOICE | `INFO` | DEBUG, INFO, WARNING, ERROR |
| `--log-file` | | TEXT | none | Write logs to file |
| `--no-progress` | | FLAG | | Disable progress bar |
| `--config` | `-C` | PATH | none | Config file path |
| `--cache` | | FLAG | `false` | Enable response caching |
| `--cache-dir` | | PATH | `.ergane_cache` | Cache directory |
| `--cache-ttl` | | INT | `3600` | Cache TTL in seconds |
| `--auth-mode` | | CHOICE | none | Override auth mode from config (`auto` = headless, `manual` = visible browser) |
| `--js` | | FLAG | `false` | Enable JavaScript rendering via Playwright (requires `ergane[js]`) |
| `--js-wait` | | CHOICE | `networkidle` | Playwright page wait strategy: `networkidle`, `domcontentloaded`, `load` |

---

## Presets

Ergane ships with 8 built-in presets for popular sites. Each preset bundles the
start URL, CSS selectors, and pagination logic.

| Preset | Site | Fields |
|---|---|---|
| `hacker-news` | news.ycombinator.com | title, link, score, author, comments |
| `github-repos` | github.com/search | name, description, stars, language, link |
| `reddit` | old.reddit.com | title, subreddit, score, author, comments, link |
| `quotes` | quotes.toscrape.com | quote, author, tags |
| `amazon-products` | amazon.com | title, price, rating, reviews, link |
| `ebay-listings` | ebay.com | title, price, condition, shipping, link |
| `wikipedia-articles` | en.wikipedia.org | title, link |
| `bbc-news` | bbc.com/news | title, summary, link |

List all presets and their details:

```bash
ergane --list-presets
```

Use a preset:

```bash
ergane --preset quotes -o quotes.json -n 200
```

---

## Custom Schemas

Define custom extraction rules in a YAML file and pass it with `--schema`/`-s`.

### YAML Format

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

### Field Properties

- **`selector`** — CSS selector to locate the element(s).
- **`type`** — Data type for the extracted value.
- **`attr`** — Extract an HTML attribute instead of text content (e.g., `src`, `href`).
- **`coerce`** — When `true`, apply type coercion (strip currency symbols, parse comma-separated numbers, convert yes/no to booleans).

### Supported Types

| Type | Aliases |
|---|---|
| `str` | `string` |
| `int` | `integer` |
| `float` | |
| `bool` | `boolean` |
| `datetime` | |
| `list[T]` | Where T is any scalar type above |

Coercion examples: `"$19.99"` becomes `19.99`, `"1,234"` becomes `1234`, `"yes"` becomes `True`.

Every extracted record automatically includes two fields: `url` (str) and `crawled_at` (datetime).

### Testing a Schema

Always validate your schema against a live page before running a full crawl:

```bash
ergane test-schema -u https://example.com/product/123 -s product.yaml
```

This prints a table showing each field name, its selector, and the extracted
value (or `MISSING` if the selector matched nothing).

---

## Output Formats

Ergane supports 6 output formats:

| Format | Extension | Notes |
|---|---|---|
| Parquet | `.parquet` | Default. Columnar, compressed, typed. |
| CSV | `.csv` | Universal compatibility. |
| Excel | `.xlsx` | Single-sheet workbook. |
| JSON | `.json` | Array of objects. |
| JSONL | `.jsonl` | One JSON object per line. Streamable. |
| SQLite | `.sqlite` | One table, named after the output file stem. |

Format is auto-detected from the file extension. Override with `--format`/`-f`:

```bash
# Force JSON output regardless of file extension
ergane -u https://example.com -o data.txt --format json
```

---

## Caching and Checkpoints

### Response Caching

Enable HTTP response caching to avoid re-fetching pages during development or
repeated runs:

```bash
ergane -u https://example.com --cache --cache-ttl 7200 -o data.csv
```

- `--cache` enables caching (off by default).
- `--cache-dir` sets the cache directory (default: `.ergane_cache`).
- `--cache-ttl` sets the time-to-live in seconds (default: `3600`).

### Checkpoints and Resume

For long-running crawls, Ergane saves progress at regular intervals:

```bash
# Save a checkpoint every 50 pages
ergane -u https://example.com -n 5000 --checkpoint-interval 50 -o data.parquet

# Resume an interrupted crawl
ergane -u https://example.com -n 5000 --resume -o data.parquet
```

- `--checkpoint-interval` controls how often progress is saved (default: every 100 pages).
- `--resume` picks up from the last checkpoint.

---

## Authentication

Some sites require login before scraping. Ergane supports automated and manual
browser-based authentication via Playwright.

### Configuration

Add an `auth` section to your config file:

```yaml
auth:
  login_url: "https://example.com/login"
  mode: auto
  username_selector: "#username"
  password_selector: "#password"
  submit_selector: "button[type=submit]"
  username: "${ERGANE_USER}"
  password: "${ERGANE_PASS}"
  check_url: "https://example.com/dashboard"
  session_file: ".ergane_session.json"
  session_ttl: 3600
  wait_after_login: "networkidle"
```

Credentials support `${ENV_VAR}` interpolation, so secrets stay out of the
config file.

### Auth Modes

- **`auto`** — Headless Playwright browser fills in credentials automatically.
- **`manual`** — A visible browser window opens for you to log in manually. Useful for CAPTCHA-protected or MFA-enabled sites.

Override the mode from the command line:

```bash
ergane -u https://example.com --auth-mode manual -C config.yaml -o data.csv
```

### Session Management

```bash
# Log in and save the session without crawling
ergane auth login --config-file config.yaml

# Check if a saved session exists
ergane auth status

# Delete the saved session
ergane auth clear
```

Sessions are saved to `.ergane_session.json` by default. Adjust with the
`session_file` config key or `--session-file` flag.

---

## JavaScript Rendering

Sites that load content via JavaScript require browser-based rendering.

### Installation

Install the optional JS rendering dependencies:

```bash
pip install "ergane[js]"
```

This pulls in Playwright. You may also need to install browser binaries:

```bash
playwright install chromium
```

### Usage

```bash
# Render JS before extracting
ergane -u https://spa-example.com -s schema.yaml --js -o data.json

# Change the wait strategy
ergane -u https://spa-example.com --js --js-wait domcontentloaded -o data.json
```

### Wait Strategies

| Strategy | Description |
|---|---|
| `networkidle` | Wait until no network requests for 500ms (default). Best for SPAs. |
| `domcontentloaded` | Wait until the DOM is ready. Faster but may miss lazy content. |
| `load` | Wait until the `load` event fires. |

---

## Configuration File

Ergane looks for a configuration file in the following order:

1. Explicit path via `--config`/`-C`
2. `~/.ergane.yaml`
3. `./.ergane.yaml`
4. `./ergane.yaml`

The first file found is used. CLI flags always override config file values.

### Full Config Structure

```yaml
crawler:
  max_pages: 100
  max_depth: 3
  concurrency: 10
  rate_limit: 10.0
  timeout: 30.0
  same_domain: true
  respect_robots_txt: true
  proxy: null
  user_agent: null
  domain_rate_limits: {}
  cache: false
  cache_dir: .ergane_cache
  cache_ttl: 3600

defaults:
  output_format: "csv"
  checkpoint_interval: 100

logging:
  level: "INFO"
  file: null

auth:
  login_url: "https://example.com/login"
  mode: auto
  username_selector: "#username"
  password_selector: "#password"
  submit_selector: "button[type=submit]"
  username: "${ERGANE_USER}"
  password: "${ERGANE_PASS}"
  check_url: "https://example.com/dashboard"
  session_file: ".ergane_session.json"
  session_ttl: 3600
  wait_after_login: "networkidle"
```

Unknown sections or keys produce a warning in the log output.

---

## Proxy and Networking

### Proxy

Route all requests through an HTTP or HTTPS proxy:

```bash
ergane -u https://example.com --proxy http://localhost:8080 -o data.csv
```

The short form is `-x`:

```bash
ergane -u https://example.com -x http://user:pass@proxy.example.com:3128 -o data.csv
```

### Timeout

Set the per-request timeout in seconds (default: 30):

```bash
ergane -u https://example.com --timeout 60 -o data.csv
```

### Rate Limiting

Control the maximum requests per second per domain (default: 10.0):

```bash
ergane -u https://example.com --rate-limit 2.0 -o data.csv
```

Override the rate for specific domains with `--domain-rate-limit DOMAIN:RATE`. The flag is repeatable:

```bash
# 0.5 req/s for the slow site, 20 req/s for the fast CDN, global default elsewhere
ergane -u https://slow-site.com \
       --rate-limit 5.0 \
       --domain-rate-limit slow-site.com:0.5 \
       --domain-rate-limit fast-cdn.example.com:20 \
       -o data.csv
```

### Concurrency

Set the number of concurrent requests (default: 10):

```bash
ergane -u https://example.com --concurrency 5 -o data.csv
```

---

## Troubleshooting

### Empty output file

- Verify your CSS selectors match the live page. Use `test-schema` to debug:
  ```bash
  ergane test-schema -u https://example.com -s schema.yaml
  ```
- Check that the site does not require JavaScript rendering. Add `--js` if it does.
- Run with `--log-level DEBUG` to see every request and extraction step.

### Blocked by robots.txt

By default, Ergane respects `robots.txt`. If you have permission to scrape the
site, pass `--ignore-robots`:

```bash
ergane -u https://example.com --ignore-robots -o data.csv
```

### HTTP 429 (Too Many Requests)

Lower the rate limit and concurrency:

```bash
ergane -u https://example.com -r 1.0 -c 2 -o data.csv
```

### Request timeouts

Increase the timeout for slow servers:

```bash
ergane -u https://slow-site.com -t 120 -o data.csv
```

### Resuming a failed crawl

If a crawl was interrupted, resume from the last checkpoint:

```bash
ergane -u https://example.com --resume -o data.csv
```

Make sure the output path matches the original run so the checkpoint file is
found.

---

## See Also

- [Python Library Reference](python-library.md) — Use Ergane as a Python library.
- [MCP Server Reference](mcp-server.md) — Run Ergane as an MCP tool server.
