# JavaScript Rendering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add opt-in Playwright-based JavaScript rendering so ergane can scrape SPAs and dynamic sites.

**Architecture:** Extract the raw HTTP call from `Fetcher` into a `_do_request()` method, then subclass as `PlaywrightFetcher` which overrides only that method. The parent handles robots.txt, rate limiting, retries, and caching unchanged. `Crawler` selects the fetcher based on a `js=True` config flag.

**Tech Stack:** `playwright>=1.40.0` (optional extra `ergane[js]`), Chromium headless, existing httpx/asyncio stack.

---

### Task 1: Extract `_do_request()` from `Fetcher`

**Files:**
- Modify: `ergane/crawler/fetcher.py:163-172`
- Modify: `tests/test_fetcher.py` (no new tests needed — existing tests cover behaviour)

**Step 1: Add `_do_request()` to `Fetcher`**

Inside the retry loop in `fetch()`, replace the inline httpx call with a call to `_do_request()`. Add the method just above `fetch()`:

```python
async def _do_request(
    self, url: str, headers: dict
) -> tuple[int, str, str, dict[str, str]]:
    """Perform the actual network request.

    Returns:
        (status_code, content, final_url, response_headers)

    Raises:
        httpx.TimeoutException: on timeout
        httpx.HTTPError: on other HTTP errors
    """
    resp = await self._client.get(url, headers=headers)
    return (
        resp.status_code,
        resp.text if resp.status_code == 200 else "",
        str(resp.url),
        dict(resp.headers),
    )
```

**Step 2: Update the retry loop in `fetch()` to call `_do_request()`**

Replace lines 163-172 in `fetcher.py`:

```python
# Before:
extra_headers = request.metadata.get("headers", {})
resp = await self._client.get(request.url, headers=extra_headers)
response = CrawlResponse(
    url=str(resp.url),
    status_code=resp.status_code,
    content=resp.text if resp.status_code == 200 else "",
    headers=dict(resp.headers),
    request=request,
)

# After:
extra_headers = request.metadata.get("headers", {})
status_code, content, final_url, resp_headers = await self._do_request(
    request.url, extra_headers
)
response = CrawlResponse(
    url=final_url,
    status_code=status_code,
    content=content,
    headers=resp_headers,
    request=request,
)
```

**Step 3: Run existing fetcher tests**

```bash
uv run pytest tests/test_fetcher.py -v
```

Expected: all pass (behaviour unchanged).

**Step 4: Commit**

```bash
git add ergane/crawler/fetcher.py
git commit -m "refactor(fetcher): extract _do_request() for subclass override"
```

---

### Task 2: Add `js` fields to `CrawlConfig`

**Files:**
- Modify: `ergane/models/schemas.py:3,15-35`

**Step 1: Add `Literal` to imports and two new fields**

In `ergane/models/schemas.py`, update the `typing` import and add fields to `CrawlConfig`:

```python
# Change line 3:
from typing import Any, Literal, Type

# Add inside CrawlConfig after the cache_ttl field:
# JavaScript rendering
js: bool = Field(default=False, description="Enable Playwright JS rendering")
js_wait: Literal["networkidle", "domcontentloaded", "load"] = Field(
    default="networkidle",
    description="Playwright page wait strategy",
)
```

**Step 2: Run model tests**

```bash
uv run pytest tests/test_models.py -v 2>/dev/null || uv run pytest tests/ -k "config" -v
```

Expected: pass (new fields have defaults, no breaking changes).

**Step 3: Commit**

```bash
git add ergane/models/schemas.py
git commit -m "feat(config): add js and js_wait fields to CrawlConfig"
```

---

### Task 3: Create `PlaywrightFetcher`

**Files:**
- Create: `ergane/crawler/playwright_fetcher.py`
- Create: `tests/test_playwright_fetcher.py`

**Step 1: Write the failing tests first**

Create `tests/test_playwright_fetcher.py`:

```python
"""Tests for PlaywrightFetcher — skipped if playwright is not installed."""

import pytest

pytest.importorskip("playwright", reason="playwright not installed; run: pip install ergane[js] && playwright install chromium")

from ergane.crawler.playwright_fetcher import PlaywrightFetcher
from ergane.models import CrawlConfig, CrawlRequest


@pytest.fixture
def js_config():
    return CrawlConfig(
        max_requests_per_second=100.0,
        request_timeout=30.0,
        respect_robots_txt=False,
        js=True,
        js_wait="load",
    )


class TestPlaywrightFetcherLifecycle:
    async def test_context_manager_opens_and_closes(self, js_config):
        """Browser launches in __aenter__ and closes in __aexit__."""
        async with PlaywrightFetcher(js_config) as fetcher:
            assert fetcher._browser is not None
            assert fetcher._browser.is_connected()
        # After exit, browser is disconnected
        assert not fetcher._browser.is_connected()

    async def test_fetch_without_init_raises(self, js_config):
        """Calling fetch() without context manager raises RuntimeError."""
        fetcher = PlaywrightFetcher(js_config)
        request = CrawlRequest(url="http://example.com", depth=0, priority=0)
        with pytest.raises(RuntimeError, match="not initialized"):
            await fetcher.fetch(request)


class TestPlaywrightFetcherRendering:
    async def test_renders_static_page(self, js_config, mock_server):
        """PlaywrightFetcher returns HTML content from a static page."""
        request = CrawlRequest(url=f"{mock_server}/", depth=0, priority=0)
        async with PlaywrightFetcher(js_config) as fetcher:
            response = await fetcher.fetch(request)
        assert response.status_code == 200
        assert "<h1>" in response.content
        assert response.error is None

    async def test_returns_rendered_html(self, js_config, mock_server):
        """Response content is full HTML (not empty body)."""
        request = CrawlRequest(url=f"{mock_server}/page1", depth=0, priority=0)
        async with PlaywrightFetcher(js_config) as fetcher:
            response = await fetcher.fetch(request)
        assert "Page 1" in response.content

    async def test_404_page(self, js_config, mock_server):
        """Non-200 responses are handled gracefully."""
        request = CrawlRequest(url=f"{mock_server}/status/404", depth=0, priority=0)
        async with PlaywrightFetcher(js_config) as fetcher:
            response = await fetcher.fetch(request)
        assert response.status_code == 404
        assert response.content == ""

    async def test_js_wait_networkidle(self, mock_server):
        """networkidle wait strategy works."""
        config = CrawlConfig(
            request_timeout=30.0,
            respect_robots_txt=False,
            js=True,
            js_wait="networkidle",
        )
        request = CrawlRequest(url=f"{mock_server}/", depth=0, priority=0)
        async with PlaywrightFetcher(config) as fetcher:
            response = await fetcher.fetch(request)
        assert response.status_code == 200

    async def test_js_wait_domcontentloaded(self, mock_server):
        """domcontentloaded wait strategy works."""
        config = CrawlConfig(
            request_timeout=30.0,
            respect_robots_txt=False,
            js=True,
            js_wait="domcontentloaded",
        )
        request = CrawlRequest(url=f"{mock_server}/", depth=0, priority=0)
        async with PlaywrightFetcher(config) as fetcher:
            response = await fetcher.fetch(request)
        assert response.status_code == 200


class TestPlaywrightFetcherTimeout:
    async def test_timeout_returns_error_response(self, js_config, mock_server):
        """Timeout during navigation returns CrawlResponse with error, not exception."""
        config = CrawlConfig(
            request_timeout=0.001,  # 1ms — will always time out
            respect_robots_txt=False,
            js=True,
            js_wait="load",
        )
        request = CrawlRequest(url=f"{mock_server}/delay/5", depth=0, priority=0)
        async with PlaywrightFetcher(config) as fetcher:
            response = await fetcher.fetch(request)
        assert response.status_code == 0
        assert response.error is not None
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_playwright_fetcher.py -v
```

Expected: `ImportError` skip (playwright not installed) OR `ModuleNotFoundError` for `playwright_fetcher`.

**Step 3: Create `ergane/crawler/playwright_fetcher.py`**

```python
"""Playwright-based fetcher for JavaScript-rendered pages."""

from __future__ import annotations

import httpx

try:
    from playwright.async_api import (
        Browser,
        Error as PlaywrightError,
        Playwright,
        TimeoutError as PlaywrightTimeoutError,
        async_playwright,
    )
except ImportError as exc:
    raise ImportError(
        "Playwright is required for JS rendering. "
        "Install with: pip install ergane[js] && playwright install chromium"
    ) from exc

from ergane.crawler.fetcher import Fetcher
from ergane.logging import get_logger
from ergane.models import CrawlConfig

_logger = get_logger()


class PlaywrightFetcher(Fetcher):
    """Fetcher that renders pages with a headless Chromium browser.

    Inherits robots.txt checking, rate limiting, retries, and response
    caching from Fetcher. Only the actual network call is overridden.
    """

    def __init__(self, config: CrawlConfig) -> None:
        super().__init__(config)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "PlaywrightFetcher":
        # Initialize httpx client (needed for robots.txt fetching in parent)
        await super().__aenter__()
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to launch Playwright browser. "
                f"Did you run 'playwright install chromium'? Error: {exc}"
            ) from exc
        _logger.debug("Playwright browser launched")
        return self

    async def __aexit__(self, *args) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        await super().__aexit__(*args)
        _logger.debug("Playwright browser closed")

    async def _do_request(
        self, url: str, headers: dict
    ) -> tuple[int, str, str, dict[str, str]]:
        """Render the page with Playwright and return its HTML content.

        Playwright TimeoutError and other errors are converted to httpx
        exceptions so the parent fetch() retry logic applies unchanged.
        """
        assert self._browser is not None, "PlaywrightFetcher not initialized"

        page = await self._browser.new_page(extra_http_headers=headers)
        try:
            response = await page.goto(
                url,
                wait_until=self.config.js_wait,
                timeout=self.config.request_timeout * 1000,  # ms
            )
            if response is None:
                return 0, "", url, {}

            content = await page.content()
            status = response.status
            return (
                status,
                content if status == 200 else "",
                page.url,
                dict(response.headers),
            )
        except PlaywrightTimeoutError as exc:
            # Map to httpx exception so parent retry logic handles it
            raise httpx.TimeoutException(str(exc)) from exc
        except PlaywrightError as exc:
            raise httpx.HTTPError(str(exc)) from exc
        finally:
            await page.close()
```

**Step 4: Install playwright and run tests**

```bash
uv run playwright install chromium
uv run pytest tests/test_playwright_fetcher.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add ergane/crawler/playwright_fetcher.py tests/test_playwright_fetcher.py
git commit -m "feat(fetcher): add PlaywrightFetcher for JS rendering"
```

---

### Task 4: Wire `PlaywrightFetcher` into `Crawler`

**Files:**
- Modify: `ergane/crawler/engine.py:53-95` (`__init__`), `157-161` (`__aenter__`), `378-382` (`_crawl_iter`)

**Step 1: Write failing test**

Add to `tests/test_engine.py`:

```python
@pytest.mark.asyncio
async def test_crawler_uses_playwright_when_js_true(engine_server: str):
    """Crawler instantiates PlaywrightFetcher when js=True."""
    pytest.importorskip("playwright")
    from ergane.crawler.playwright_fetcher import PlaywrightFetcher

    async with Crawler(
        urls=[f"{engine_server}/"],
        max_pages=1,
        max_depth=0,
        js=True,
        js_wait="load",
        respect_robots_txt=False,
    ) as c:
        assert isinstance(c._fetcher, PlaywrightFetcher)
        results = await c.run()
    assert len(results) >= 1
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_engine.py::test_crawler_uses_playwright_when_js_true -v
```

Expected: FAIL — `Crawler.__init__` does not accept `js` param.

**Step 3: Update `Crawler.__init__`**

Add `js` and `js_wait` parameters and include them in `cfg_kwargs`:

```python
def __init__(
    self,
    urls: list[str],
    *,
    # ... existing params ...
    js: bool = False,
    js_wait: str = "networkidle",
    # ... rest of params ...
) -> None:
    if config is not None:
        self._config = config
    else:
        cfg_kwargs: dict = {
            # ... existing kwargs ...
            "js": js,
            "js_wait": js_wait,
        }
        # ...
```

**Step 4: Update `__aenter__` to select the right fetcher**

```python
async def __aenter__(self) -> Crawler:
    if self._config.js:
        from ergane.crawler.playwright_fetcher import PlaywrightFetcher
        self._fetcher = PlaywrightFetcher(self._config)
    else:
        self._fetcher = Fetcher(self._config)
    await self._fetcher.__aenter__()
    self._owns_fetcher = True
    return self
```

**Step 5: Update `_crawl_iter` fetcher creation** (the non-context-manager path, around line 379):

```python
if self._fetcher is None:
    if self._config.js:
        from ergane.crawler.playwright_fetcher import PlaywrightFetcher
        self._fetcher = PlaywrightFetcher(self._config)
    else:
        self._fetcher = Fetcher(self._config)
    await self._fetcher.__aenter__()
    owns_fetcher_locally = True
```

**Step 6: Run tests**

```bash
uv run pytest tests/test_engine.py -v
```

Expected: all pass including new test.

**Step 7: Commit**

```bash
git add ergane/crawler/engine.py
git commit -m "feat(engine): select PlaywrightFetcher when js=True"
```

---

### Task 5: Add `js` optional extra to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml:37-50`

**Step 1: Add the extra**

```toml
[project.optional-dependencies]
mcp = [
    "mcp[cli]>=1.0.0",
]
js = [
    "playwright>=1.40.0",
]
dev = [
    # ... existing dev deps ...
]
```

**Step 2: Verify package installs cleanly without the extra**

```bash
uv pip install -e "." --no-deps 2>&1 | grep -i error || echo "OK"
```

Expected: `OK` (no errors).

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add js optional extra for playwright"
```

---

### Task 6: Add `--js` and `--js-wait` to the CLI

**Files:**
- Modify: `ergane/main.py` — add two options to `crawl` command, pass through to `Crawler`

**Step 1: Write failing CLI test**

Add to `tests/test_mcp.py` (in `TestCLI`):

```python
def test_js_flag_accepted(self, mock_server):
    """--js flag is accepted without error (import may skip if playwright absent)."""
    from ergane.main import cli
    runner = CliRunner()
    # We only test that the flag is parsed — don't actually launch a browser
    result = runner.invoke(cli, ["crawl", "--help"])
    assert "--js" in result.output

def test_js_wait_choices(self):
    """--js-wait only accepts valid strategies."""
    from ergane.main import cli
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["crawl", "-u", "http://example.com", "--js-wait", "invalid"],
    )
    assert result.exit_code != 0
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_mcp.py::TestCLI::test_js_flag_accepted -v
```

Expected: FAIL — `--js` not in help output.

**Step 3: Add options to `crawl` command**

After the `--cache-ttl` option, add:

```python
@click.option(
    "--js",
    is_flag=True,
    default=False,
    help="Enable JavaScript rendering via Playwright (requires ergane[js]).",
)
@click.option(
    "--js-wait",
    type=click.Choice(["networkidle", "domcontentloaded", "load"]),
    default="networkidle",
    show_default=True,
    help="Playwright page wait strategy.",
)
```

Add `js: bool` and `js_wait: str` to the `crawl` function signature, and pass them to `Crawler`:

```python
crawler = Crawler(
    # ... existing args ...
    js=js,
    js_wait=js_wait,
)
```

**Step 4: Run CLI tests**

```bash
uv run pytest tests/test_mcp.py::TestCLI -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add ergane/main.py tests/test_mcp.py
git commit -m "feat(cli): add --js and --js-wait flags"
```

---

### Task 7: Add `js` parameters to MCP tools

**Files:**
- Modify: `ergane/mcp/tools.py`
- Modify: `tests/test_mcp.py`

**Step 1: Write failing MCP tests**

Add to `tests/test_mcp.py`:

```python
class TestMCPJsParams:
    """Verify MCP tools accept js/js_wait parameters without error."""

    async def test_extract_tool_accepts_js_false(self, mock_server):
        """extract_tool works normally when js=False (default)."""
        result = await extract_tool(
            url=f"{mock_server}/",
            selectors={"title": "h1"},
            js=False,
        )
        data = json.loads(result)
        assert "title" in data

    async def test_crawl_tool_accepts_js_false(self, mock_server):
        """crawl_tool works normally when js=False (default)."""
        result = await crawl_tool(
            urls=[f"{mock_server}/"],
            max_pages=1,
            max_depth=0,
            js=False,
        )
        data = json.loads(result)
        assert isinstance(data, list)

    async def test_scrape_preset_tool_accepts_js_false(self):
        """scrape_preset_tool accepts js param (invalid preset just returns error)."""
        result = await scrape_preset_tool(preset="nonexistent", js=False)
        data = json.loads(result)
        assert "error_code" in data
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_mcp.py::TestMCPJsParams -v
```

Expected: FAIL — `js` is not a valid parameter.

**Step 3: Update `extract_tool`**

```python
async def extract_tool(
    url: str,
    selectors: dict[str, str] | None = None,
    schema_yaml: str | None = None,
    js: bool = False,
    js_wait: str = "networkidle",
) -> str:
    # ...
    config = CrawlConfig(
        max_requests_per_second=10.0,
        max_concurrent_requests=1,
        request_timeout=60.0,
        js=js,
        js_wait=js_wait,
    )
    request = CrawlRequest(url=url, depth=0, priority=0)
    fetcher_cls = _get_fetcher_cls(js)
    async with fetcher_cls(config) as fetcher:
        response = await fetcher.fetch(request)
    # ... rest unchanged
```

Add a helper at the top of `tools.py`:

```python
def _get_fetcher_cls(js: bool):
    """Return PlaywrightFetcher if js=True, else Fetcher."""
    if js:
        from ergane.crawler.playwright_fetcher import PlaywrightFetcher
        return PlaywrightFetcher
    from ergane.crawler.fetcher import Fetcher
    return Fetcher
```

**Step 4: Update `scrape_preset_tool`**

```python
async def scrape_preset_tool(
    preset: str,
    max_pages: int = 5,
    js: bool = False,
    js_wait: str = "networkidle",
) -> str:
    # ...
    async with Crawler(
        urls=preset_config.start_urls,
        schema=schema,
        max_pages=max_pages,
        max_depth=preset_config.defaults.get("max_depth", 1),
        concurrency=5,
        rate_limit=5.0,
        timeout=60.0,
        js=js,
        js_wait=js_wait,
    ) as crawler:
```

**Step 5: Update `crawl_tool`**

```python
async def crawl_tool(
    urls: list[str],
    schema_yaml: str | None = None,
    max_pages: int = 10,
    max_depth: int = 1,
    concurrency: int = 5,
    output_format: str = "json",
    js: bool = False,
    js_wait: str = "networkidle",
) -> str:
    # ...
    async with Crawler(
        urls=urls,
        schema=schema,
        max_pages=max_pages,
        max_depth=max_depth,
        concurrency=concurrency,
        rate_limit=5.0,
        timeout=60.0,
        js=js,
        js_wait=js_wait,
    ) as crawler:
```

**Step 6: Run MCP tests**

```bash
uv run pytest tests/test_mcp.py -v
```

Expected: all pass.

**Step 7: Commit**

```bash
git add ergane/mcp/tools.py tests/test_mcp.py
git commit -m "feat(mcp): add js and js_wait params to extract, crawl, scrape_preset tools"
```

---

### Task 8: Full test suite + final commit

**Step 1: Run the full suite**

```bash
uv run pytest tests/ --ignore=tests/test_playwright_fetcher.py -q
```

Expected: all existing tests pass.

**Step 2: Run Playwright tests (if installed)**

```bash
uv run pytest tests/test_playwright_fetcher.py -v
```

Expected: all pass (skip gracefully if playwright not installed).

**Step 3: Verify `--js` appears in CLI help**

```bash
uv run ergane crawl --help | grep js
```

Expected:
```
--js          Enable JavaScript rendering via Playwright
--js-wait     Playwright page wait strategy.
```

**Step 4: Push branch and open PR**

```bash
git push -u origin feat/js-rendering
gh pr create \
  --title "feat: JavaScript rendering via Playwright" \
  --body "Adds opt-in Playwright-based JS rendering. See docs/plans/2026-02-21-js-rendering-design.md."
```
