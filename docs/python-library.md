# Ergane Python Library Guide

Ergane is an async web scraper for Python 3.10+ built on httpx, selectolax, Pydantic, and Polars. This guide covers the full Python API.

For CLI usage, see [cli.md](cli.md). For the MCP server, see [mcp-server.md](mcp-server.md).

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Crawler](#crawler)
3. [One-shot crawl()](#one-shot-crawl)
4. [Typed Extraction](#typed-extraction)
5. [YAML Schemas](#yaml-schemas)
6. [Hooks](#hooks)
7. [Authentication](#authentication)
8. [JavaScript Rendering](#javascript-rendering)
9. [Output and Pipeline](#output-and-pipeline)
10. [Configuration](#configuration)
11. [Data Models](#data-models)
12. [Advanced](#advanced)

---

## Quick Start

Install Ergane:

```bash
pip install ergane
```

Crawl a site and extract structured data in under 20 lines:

```python
import asyncio
from pydantic import BaseModel
from ergane import Crawler, selector

class Article(BaseModel):
    title: str = selector("h1.article-title")
    author: str = selector("span.author-name")
    summary: str = selector("p.summary")

async def main():
    async with Crawler(
        urls=["https://example.com/blog"],
        schema=Article,
        max_pages=50,
    ) as crawler:
        items = await crawler.run()
        for item in items:
            print(f"{item.title} by {item.author}")

asyncio.run(main())
```

---

## Crawler

The `Crawler` class is the primary interface for programmatic crawling. It must be used as an async context manager.

### Constructor Parameters

All parameters are keyword-only except `urls`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `urls` | `list[str]` | *(required)* | Seed URL(s) to start crawling |
| `schema` | `type[BaseModel] \| None` | `None` | Pydantic model for typed extraction |
| `concurrency` | `int` | `10` | Number of concurrent workers |
| `max_pages` | `int` | `100` | Maximum pages to crawl |
| `max_depth` | `int` | `3` | Maximum link-follow depth |
| `rate_limit` | `float` | `10.0` | Requests per second per domain |
| `timeout` | `float` | `30.0` | HTTP request timeout (seconds) |
| `same_domain` | `bool` | `True` | Only follow links on the seed domain |
| `respect_robots_txt` | `bool` | `True` | Obey robots.txt |
| `user_agent` | `str \| None` | `None` | Custom user agent (default: `Ergane/{version}`) |
| `proxy` | `str \| None` | `None` | HTTP/HTTPS proxy URL |
| `domain_rate_limits` | `dict[str, float] \| None` | `None` | Per-domain rate overrides (req/sec). Hostname keys override `rate_limit` for that domain. |
| `hooks` | `list[CrawlHook] \| None` | `None` | List of hook instances |
| `output` | `str \| Path \| None` | `None` | File path to write results |
| `output_format` | `OutputFormat` | `"auto"` | `csv`, `excel`, `parquet`, `json`, `jsonl`, `sqlite` |
| `cache` | `bool` | `False` | Enable SQLite response caching |
| `cache_dir` | `Path` | `Path(".ergane_cache")` | Cache directory |
| `cache_ttl` | `int` | `3600` | Cache TTL in seconds |
| `checkpoint_interval` | `int` | `0` | Save checkpoint every N pages (0=disabled) |
| `checkpoint_path` | `str \| Path \| None` | `None` | Checkpoint file path |
| `resume_from` | `CrawlerCheckpoint \| None` | `None` | Resume from a checkpoint |
| `config` | `CrawlConfig \| None` | `None` | Provide a CrawlConfig directly (overrides individual params) |
| `auth` | `AuthConfig \| None` | `None` | Authentication configuration |
| `js` | `bool` | `False` | Enable JavaScript rendering via Playwright |
| `js_wait` | `str` | `"networkidle"` | Playwright wait strategy |

### Methods

#### `async run() -> list[BaseModel]`

Execute the crawl and return all extracted items as a list.

```python
async with Crawler(urls=["https://example.com"], schema=MyModel) as crawler:
    items = await crawler.run()
    print(f"Extracted {len(items)} items")
```

#### `async stream() -> AsyncIterator[BaseModel]`

Yield items as they arrive, useful for large crawls or real-time processing.

```python
async with Crawler(urls=["https://example.com"], schema=MyModel) as crawler:
    async for item in crawler.stream():
        print(item)
```

#### `shutdown() -> None`

Signal the crawler to stop gracefully. Outstanding requests will complete but no new URLs will be enqueued.

```python
async with Crawler(urls=["https://example.com"], max_pages=1000) as crawler:
    count = 0
    async for item in crawler.stream():
        count += 1
        if count >= 50:
            crawler.shutdown()
            break
```

#### `stats` property

Returns a dictionary with crawl statistics:

```python
async with Crawler(urls=["https://example.com"]) as crawler:
    await crawler.run()
    print(crawler.stats)
    # {
    #     "pages_crawled": 42,
    #     "items_extracted": 38,
    #     "errors": 2,
    #     "cache_hits": 0,
    #     "elapsed": 12.5,
    #     "pages_per_sec": 3.36,
    # }
```

---

## One-shot crawl()

The `crawl()` convenience function wraps `Crawler` for simple use cases where you do not need streaming or fine-grained control.

```python
async def crawl(
    urls: list[str],
    *,
    schema: type[BaseModel] | None = None,
    **kwargs,  # same keyword arguments as Crawler
) -> list[BaseModel]:
```

Example:

```python
import asyncio
from ergane import crawl

async def main():
    items = await crawl(
        urls=["https://example.com"],
        max_pages=10,
        max_depth=1,
    )
    for item in items:
        print(item.url, item.title)

asyncio.run(main())
```

All keyword arguments accepted by the `Crawler` constructor can be passed to `crawl()`.

---

## Typed Extraction

Define a Pydantic model with `selector()` field defaults to extract structured data from every crawled page.

### The `selector()` helper

```python
from ergane import selector

def selector(
    css: str,
    *,
    coerce: bool = False,
    attr: str | None = None,
    default: Any = ...,
) -> Any:
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `css` | `str` | *(required)* | CSS selector string |
| `coerce` | `bool` | `False` | Aggressive type coercion (e.g., `"$19.99"` becomes `19.99`) |
| `attr` | `str \| None` | `None` | Extract an HTML attribute instead of text content (`"href"`, `"src"`, etc.) |
| `default` | `Any` | `...` | Default value if the selector matches nothing. If omitted and nothing matches, extraction raises an error. |

### Example

```python
from pydantic import BaseModel
from ergane import Crawler, selector

class Product(BaseModel):
    name: str = selector("h1.product-title")
    price: float = selector("span.price", coerce=True)
    image_url: str = selector("img.product", attr="src")
    in_stock: bool = selector("span.stock-status", coerce=True, default=False)
    tags: list[str] = selector("span.tag")

async def main():
    async with Crawler(
        urls=["https://shop.example.com/products"],
        schema=Product,
        max_pages=200,
    ) as crawler:
        products = await crawler.run()
        for p in products:
            print(f"{p.name}: ${p.price:.2f} (in stock: {p.in_stock})")
```

When `coerce=True`, Ergane strips currency symbols, commas, and other non-numeric characters before casting to the target type. This is particularly useful for prices, percentages, and quantities.

When `attr` is set, Ergane extracts the named HTML attribute from the matched element rather than its text content. Common uses include `attr="href"` for links and `attr="src"` for images.

---

## YAML Schemas

For situations where you prefer not to define a Python model -- for example, when schemas are generated dynamically or stored as configuration files -- Ergane supports YAML schema definitions.

### Loading a YAML Schema

```python
from ergane import load_schema_from_yaml

# From a file
ProductModel = load_schema_from_yaml("schemas/product.yaml")

# From a string
from ergane.schema.yaml_loader import load_schema_from_string

schema_text = """
name: ArticleItem
fields:
  title:
    selector: "h1"
    type: str
  body:
    selector: "div.content"
    type: str
"""
ArticleModel = load_schema_from_string(schema_text)
```

Both functions return a `type[BaseModel]` that can be passed directly to `Crawler(schema=...)`.

### YAML Format Reference

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

Supported types: `str`, `string`, `int`, `integer`, `float`, `bool`, `boolean`, `datetime`, `list[T]` (where `T` is any supported scalar type).

### Using YAML Schemas with the Crawler

```python
import asyncio
from ergane import Crawler, load_schema_from_yaml

async def main():
    schema = load_schema_from_yaml("schemas/product.yaml")
    async with Crawler(
        urls=["https://shop.example.com"],
        schema=schema,
        max_pages=100,
    ) as crawler:
        items = await crawler.run()
        for item in items:
            print(item.model_dump())

asyncio.run(main())
```

---

## Hooks

Hooks let you intercept and modify requests and responses at every stage of the crawl pipeline.

### The CrawlHook Protocol

```python
class CrawlHook(Protocol):
    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None: ...
    async def on_response(self, response: CrawlResponse) -> CrawlResponse | None: ...
```

- Returning the (possibly modified) object passes it to the next hook.
- Returning `None` drops the request or response entirely.

### BaseHook

`BaseHook` is a convenience base class. Override only the methods you need; the default implementations return the object unchanged.

```python
from ergane import BaseHook, CrawlRequest, CrawlResponse

class MyHook(BaseHook):
    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None:
        # Add a custom header via metadata
        request.metadata["custom_header"] = "value"
        return request

    async def on_response(self, response: CrawlResponse) -> CrawlResponse | None:
        if response.status_code == 404:
            return None  # drop 404 responses
        return response
```

### Built-in Hooks

Import built-in hooks from `ergane.crawler.hooks`:

```python
from ergane.crawler.hooks import LoggingHook, AuthHeaderHook, StatusFilterHook
```

**LoggingHook** -- Logs all requests and responses at DEBUG level.

```python
crawler = Crawler(
    urls=["https://example.com"],
    hooks=[LoggingHook()],
)
```

**AuthHeaderHook** -- Injects custom headers into every request.

```python
crawler = Crawler(
    urls=["https://api.example.com"],
    hooks=[AuthHeaderHook(headers={"Authorization": "Bearer sk-abc123"})],
)
```

**StatusFilterHook** -- Discards responses outside a set of allowed status codes.

```python
# Only keep 200 and 201 responses
crawler = Crawler(
    urls=["https://example.com"],
    hooks=[StatusFilterHook(allowed={200, 201})],
)
```

The default allowed set is `{200}`.

### Composing Hooks

Hooks run in list order. For requests, each hook receives the output of the previous one. This makes composition straightforward:

```python
async with Crawler(
    urls=["https://api.example.com/data"],
    hooks=[
        AuthHeaderHook(headers={"Authorization": "Bearer token"}),
        StatusFilterHook(allowed={200}),
        LoggingHook(),
    ],
) as crawler:
    items = await crawler.run()
```

In this example, `AuthHeaderHook` adds the header first, then `StatusFilterHook` filters responses, and `LoggingHook` logs whatever passes through.

---

## Authentication

Ergane supports browser-based authentication for sites that require login. It uses Playwright to automate the login flow and captures session cookies.

### AuthConfig

```python
from ergane import AuthConfig

auth = AuthConfig(
    login_url="https://example.com/login",
    username_selector="#email",
    password_selector="#password",
    submit_selector="button[type=submit]",
    username="${SITE_USERNAME}",
    password="${SITE_PASSWORD}",
    check_url="https://example.com/dashboard",
    session_ttl=7200,
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `login_url` | `str` | *(required)* | URL of the login page |
| `mode` | `Literal["auto", "manual"]` | `"auto"` | `auto` uses a headless browser; `manual` opens a visible browser for interactive login |
| `username_selector` | `str \| None` | `None` | CSS selector for the username field |
| `password_selector` | `str \| None` | `None` | CSS selector for the password field |
| `submit_selector` | `str \| None` | `None` | CSS selector for the submit button |
| `username` | `str \| None` | `None` | Username value (supports `${ENV_VAR}` interpolation) |
| `password` | `str \| None` | `None` | Password value (supports `${ENV_VAR}` interpolation) |
| `check_url` | `str \| None` | `None` | URL to verify the session is still valid |
| `session_file` | `str` | `".ergane_session.json"` | Path to store the session |
| `session_ttl` | `int` | `3600` | Session TTL in seconds |
| `wait_after_login` | `str \| None` | `None` | Playwright wait condition after login: `"networkidle"`, `"load"`, or a CSS selector to wait for |

### Environment Variable Interpolation

Use `${ENV_VAR}` syntax in the `username` and `password` fields. Ergane resolves these at runtime from the process environment:

```python
auth = AuthConfig(
    login_url="https://example.com/login",
    username="${MY_APP_USER}",
    password="${MY_APP_PASS}",
)
```

### AuthManager

For lower-level control, use `AuthManager` directly:

```python
from ergane import AuthConfig, AuthManager

auth_config = AuthConfig(login_url="https://example.com/login")
manager = AuthManager(auth_config)

# Authenticate and get cookies
cookies = await manager.authenticate()
```

### Using Authentication with the Crawler

```python
async with Crawler(
    urls=["https://example.com/protected"],
    schema=MyModel,
    auth=AuthConfig(
        login_url="https://example.com/login",
        username_selector="#user",
        password_selector="#pass",
        submit_selector="#login-btn",
        username="${SITE_USER}",
        password="${SITE_PASS}",
    ),
) as crawler:
    items = await crawler.run()
```

---

## JavaScript Rendering

Some websites require JavaScript execution to render content. Ergane integrates with Playwright to handle these sites.

### Installation

Install Ergane with the `js` extra and set up Playwright browsers:

```bash
pip install ergane[js]
playwright install chromium
```

### Usage

Enable JavaScript rendering with the `js` parameter:

```python
async with Crawler(
    urls=["https://spa-example.com"],
    schema=MyModel,
    js=True,
) as crawler:
    items = await crawler.run()
```

### Wait Strategies

The `js_wait` parameter controls when Playwright considers the page loaded:

| Value | Behavior |
|-------|----------|
| `"networkidle"` | Wait until there are no network connections for 500ms (default) |
| `"domcontentloaded"` | Wait until the `DOMContentLoaded` event fires |
| `"load"` | Wait until the `load` event fires |

```python
async with Crawler(
    urls=["https://spa-example.com"],
    schema=MyModel,
    js=True,
    js_wait="domcontentloaded",  # faster but may miss lazy-loaded content
) as crawler:
    items = await crawler.run()
```

---

## Output and Pipeline

### File Output

Write results directly to a file by specifying `output` and optionally `output_format`:

```python
async with Crawler(
    urls=["https://example.com"],
    schema=Product,
    output="results.csv",
    output_format="csv",
) as crawler:
    await crawler.run()
# results.csv is written automatically
```

Supported formats: `csv`, `excel`, `parquet`, `json`, `jsonl`, `sqlite`.

When `output_format` is `"auto"` (the default), Ergane infers the format from the file extension.

### Programmatic Pipeline Usage

The `Pipeline` class handles serialization and output. You can use it directly for custom workflows:

```python
from ergane import Pipeline
from pathlib import Path

pipeline = Pipeline(output_path=Path("output.json"), output_format="json")
await pipeline.write_batch(items)
await pipeline.finalize()
```

---

## Configuration

### CrawlConfig

`CrawlConfig` is a Pydantic model that bundles all crawler settings. Use it when you want to load configuration from a file or share settings across multiple crawls.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_requests_per_second` | `float` | `10.0` | Rate limit per domain |
| `max_concurrent_requests` | `int` | `10` | Worker concurrency |
| `request_timeout` | `float` | `30.0` | HTTP timeout in seconds |
| `max_retries` | `int` | `3` | Number of retries for failed requests |
| `retry_base_delay` | `float` | `1.0` | Base delay between retries (exponential backoff) |
| `respect_robots_txt` | `bool` | `True` | Obey robots.txt |
| `user_agent` | `str` | `"Ergane/{version}"` | User agent string |
| `max_queue_size` | `int` | `10000` | URL queue capacity |
| `batch_size` | `int` | `100` | Pipeline batch size |
| `output_schema` | `type[BaseModel] \| None` | `None` | Schema model |
| `proxy` | `str \| None` | `None` | Proxy URL |
| `domain_rate_limits` | `dict[str, float]` | `{}` | Per-domain rate overrides (req/sec). Keys are hostnames; values override `max_requests_per_second` for that domain. |
| `cache_enabled` | `bool` | `False` | Enable response caching |
| `cache_dir` | `Path` | `Path(".ergane_cache")` | Cache directory |
| `cache_ttl` | `int` | `3600` | Cache TTL in seconds |
| `js` | `bool` | `False` | Enable Playwright JS rendering |
| `js_wait` | `Literal["networkidle", "domcontentloaded", "load"]` | `"networkidle"` | Playwright wait strategy |

### Per-Domain Rate Limits

Use `domain_rate_limits` to set different rate limits for specific domains. This is useful when crawling multiple sites with different tolerance levels, or when you need to be more conservative with a slow site while staying fast elsewhere:

```python
async with Crawler(
    urls=["https://slow-site.com", "https://fast-cdn.example.com"],
    rate_limit=10.0,                         # default for all domains
    domain_rate_limits={
        "slow-site.com": 0.5,               # 1 req every 2 seconds
        "fast-cdn.example.com": 50.0,       # 50 req/s
    },
    max_pages=200,
) as crawler:
    items = await crawler.run()
```

Or via `CrawlConfig` directly:

```python
config = CrawlConfig(
    max_requests_per_second=5.0,
    domain_rate_limits={"api.example.com": 1.0},
)
```

### Loading Configuration

Use `load_config()` to load configuration from a YAML file:

```python
from ergane.config import load_config

file_config = load_config()  # searches default locations
# or
file_config = load_config(Path("my-config.yaml"))
```

`load_config()` returns a plain dictionary. It searches these locations in order (first match wins):
1. Explicit path argument
2. `~/.ergane.yaml`
3. `./.ergane.yaml`
4. `./ergane.yaml`

### CrawlOptions.from_sources()

`CrawlOptions.from_sources()` merges a file config dictionary with explicit CLI/programmatic values. File config is applied first; non-`None` explicit values take precedence:

```python
from ergane import CrawlConfig, Crawler

config = CrawlConfig(
    max_concurrent_requests=20,
    request_timeout=60.0,
    cache_enabled=True,
)

async with Crawler(
    urls=["https://example.com"],
    config=config,
) as crawler:
    items = await crawler.run()
```

When a `CrawlConfig` is passed via the `config` parameter, its values take precedence over individual constructor parameters.

---

## Data Models

### CrawlRequest

Represents a URL to be crawled.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `str` | *(required)* | URL to crawl (http/https only) |
| `depth` | `int` | `0` | Current crawl depth |
| `priority` | `int` | `0` | Priority (higher = sooner) |
| `metadata` | `dict[str, Any]` | `{}` | Arbitrary metadata carried through the pipeline |

```python
from ergane import CrawlRequest

req = CrawlRequest(url="https://example.com", depth=0, priority=10)
```

### CrawlResponse

Represents the result of fetching a URL.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `str` | *(required)* | Fetched URL |
| `status_code` | `int` | *(required)* | HTTP status code |
| `content` | `str` | `""` | Response body |
| `headers` | `dict[str, str]` | `{}` | Response headers |
| `fetched_at` | `datetime` | now (UTC) | When the response was fetched |
| `error` | `str \| None` | `None` | Error message if the request failed |
| `request` | `CrawlRequest` | *(required)* | The original request |
| `from_cache` | `bool` | `False` | Whether this response was served from cache |

### ParsedItem

A generic parsed page result, used when no schema is provided.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `str` | *(required)* | Page URL |
| `title` | `str \| None` | `None` | Page title |
| `text` | `str \| None` | `None` | Full page text content |
| `links` | `list[str]` | `[]` | Discovered links on the page |
| `extracted_data` | `dict[str, Any]` | `{}` | Additional extracted data |
| `crawled_at` | `datetime` | now (UTC) | When the page was crawled |

---

## Advanced

### Direct Component Usage

The Crawler orchestrates three components that can also be used independently: `Fetcher`, `Scheduler`, and `Pipeline`.

#### Fetcher

The `Fetcher` handles HTTP requests, rate limiting, retries, and robots.txt compliance.

```python
from ergane import Fetcher, CrawlRequest, CrawlConfig

config = CrawlConfig()
fetcher = Fetcher(config)

request = CrawlRequest(url="https://example.com")
response = await fetcher.fetch(request)
print(response.status_code, len(response.content))
```

#### Scheduler

The `Scheduler` manages the URL queue, deduplication, and priority ordering.

```python
from ergane import Scheduler, CrawlRequest

scheduler = Scheduler()
await scheduler.enqueue(CrawlRequest(url="https://example.com", priority=10))
await scheduler.enqueue(CrawlRequest(url="https://example.com/page2", priority=5))

# Highest priority first
next_request = await scheduler.dequeue()
print(next_request.url)  # https://example.com
```

#### Pipeline

The `Pipeline` handles output serialization and writing.

```python
from ergane import Pipeline
from pathlib import Path

pipeline = Pipeline(output_path=Path("data.json"), output_format="json")
await pipeline.write_batch(items)
await pipeline.finalize()
```

### ResponseCache

Enable caching to avoid re-fetching pages during development or when resuming interrupted crawls.

```python
async with Crawler(
    urls=["https://example.com"],
    schema=MyModel,
    cache=True,
    cache_dir=Path(".my_cache"),
    cache_ttl=7200,  # 2 hours
) as crawler:
    items = await crawler.run()
    print(f"Cache hits: {crawler.stats['cache_hits']}")
```

The cache uses SQLite and is stored in the directory specified by `cache_dir`. Cached responses are automatically invalidated after `cache_ttl` seconds.

### Extraction Utilities

Ergane also exports lower-level extraction functions:

```python
from ergane import extract_data, extract_links, extract_typed_data
```

- `extract_data(html, schema)` -- Extract data from an HTML string using a schema.
- `extract_links(html, base_url)` -- Extract all links from an HTML string, resolved against the base URL.
- `extract_typed_data(html, model)` -- Extract data into a typed Pydantic model.

---

## Public API Reference

All public symbols are available from the top-level `ergane` package:

```python
from ergane import (
    __version__,
    AuthConfig,
    AuthenticationError,
    AuthManager,
    BaseHook,
    crawl,
    CrawlConfig,
    CrawlHook,
    Crawler,
    CrawlRequest,
    CrawlResponse,
    extract_data,
    extract_links,
    extract_typed_data,
    Fetcher,
    load_schema_from_yaml,
    ParsedItem,
    Pipeline,
    Scheduler,
    SchemaExtractor,
    selector,
)
```
