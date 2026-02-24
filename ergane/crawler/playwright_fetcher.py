"""Playwright-based fetcher for JavaScript-rendered pages."""

from __future__ import annotations

import httpx

try:
    from playwright.async_api import (
        Browser,
        Playwright,
        async_playwright,
    )
    from playwright.async_api import (
        Error as PlaywrightError,
    )
    from playwright.async_api import (
        TimeoutError as PlaywrightTimeoutError,
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

    async def __aenter__(self) -> PlaywrightFetcher:
        # Initialize httpx client (needed for robots.txt fetching in parent)
        await super().__aenter__()
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception as exc:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            await super().__aexit__(None, None, None)
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
        if self._browser is None:
            raise RuntimeError(
                "PlaywrightFetcher not initialized"
                " — use as async context manager"
            )

        page = await self._browser.new_page(extra_http_headers=headers)
        try:
            response = await page.goto(
                url,
                wait_until=self.config.js_wait,
                timeout=self.config.request_timeout * 1000,  # ms
            )
            if response is None:
                raise httpx.HTTPError("Navigation returned no response")

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
