# JavaScript Rendering Design

**Date:** 2026-02-21
**Status:** Approved

## Problem

ergane uses selectolax for HTML parsing, which operates on raw HTTP responses. Modern sites that render content via JavaScript (SPAs, lazy-loaded data, React/Vue apps) return near-empty HTML bodies from a plain HTTP GET, making their content invisible to the scraper.

## Solution

Integrate Playwright as an opt-in headless browser fetcher. When enabled, Playwright loads the page in a real Chromium browser, executes JavaScript, waits for the page to settle, then hands the rendered HTML to the existing parser pipeline.

## Architecture

### Fetcher refactor

Extract the actual HTTP call from `Fetcher.fetch()` into a new protected method `_do_request()`. The parent `fetch()` continues to own robots.txt checking, rate limiting, response caching, and retry logic — unchanged.

```
Fetcher
├── fetch()         ← unchanged: robots, cache, rate limit, retries
└── _do_request()  ← new: httpx GET, returns (status, content, final_url)

PlaywrightFetcher(Fetcher)
├── __aenter__()   ← launches Playwright browser once per crawl
├── __aexit__()    ← closes browser
└── _do_request()  ← opens page, navigates, waits, returns rendered HTML
```

`PlaywrightFetcher` inherits all infrastructure from `Fetcher`. Only the network call itself is replaced.

### Configuration

Two new fields on `CrawlConfig`:

```python
js: bool = False
js_wait: Literal["networkidle", "domcontentloaded", "load"] = "networkidle"
```

`Crawler.__init__` accepts `js=False` and `js_wait="networkidle"`. When `js=True`, it instantiates `PlaywrightFetcher` instead of `Fetcher`.

### Browser lifecycle

- Browser launched once in `PlaywrightFetcher.__aenter__` (Chromium)
- One new page per request for isolation and clean cookie/state
- Browser closed in `PlaywrightFetcher.__aexit__`

## Packaging

Playwright is an optional extra to keep the core install light:

```toml
[project.optional-dependencies]
js = ["playwright>=1.40.0"]
```

Install: `pip install ergane[js] && playwright install chromium`

The import is guarded in `ergane/crawler/playwright_fetcher.py`:

```python
try:
    from playwright.async_api import async_playwright
except ImportError as e:
    raise ImportError(
        "Playwright is required for JS rendering. "
        "Install it with: pip install ergane[js] && playwright install"
    ) from e
```

`Crawler` imports `PlaywrightFetcher` lazily inside the `if js:` branch so the error only surfaces when JS rendering is actually requested.

## Interface

### CLI

```
--js                     Enable JavaScript rendering via Playwright
--js-wait [networkidle|domcontentloaded|load]
                         Page wait strategy (default: networkidle)
```

### Python API

```python
async with Crawler(urls=[...], js=True, js_wait="networkidle") as c:
    results = await c.run()
```

### MCP tools

`js: bool = False` and `js_wait: str = "networkidle"` added to:
- `extract_tool`
- `crawl_tool`
- `scrape_preset_tool`

## Error Handling

| Scenario | Behaviour |
|---|---|
| `playwright` not installed | `ImportError` at `PlaywrightFetcher` init with install instructions |
| `playwright install` not run | Error caught in `__aenter__` with helpful message |
| Page navigation timeout | Caught as fetch error; retries apply via inherited logic |
| Browser crash mid-crawl | Treated as fetch error; `CrawlResponse(error=...)` returned |

## Testing

- `tests/test_playwright_fetcher.py` — unit tests for `PlaywrightFetcher`: successful render, timeout, navigation error, wait strategy options, browser open/close lifecycle
- Existing tests unchanged — all use `js=False` by default
- CI: Playwright tests in a separate job gated on `playwright install chromium`
