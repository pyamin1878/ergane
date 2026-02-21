"""Tests for PlaywrightFetcher — skipped if playwright is not installed."""

import pytest

pytest.importorskip(
    "playwright",
    reason="playwright not installed; run: pip install ergane[js] && playwright install chromium",
)

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

    async def test_fetch_without_context_manager_raises(self, js_config):
        """Calling _do_request() without context manager raises AssertionError."""
        fetcher = PlaywrightFetcher(js_config)
        with pytest.raises((AssertionError, RuntimeError)):
            await fetcher._do_request("http://example.com", {})


class TestPlaywrightFetcherRendering:
    async def test_renders_static_page(self, js_config, mock_server):
        """PlaywrightFetcher returns HTML content from a static page."""
        request = CrawlRequest(url=f"{mock_server}/", depth=0, priority=0)
        async with PlaywrightFetcher(js_config) as fetcher:
            response = await fetcher.fetch(request)
        assert response.status_code == 200
        assert response.content
        assert response.error is None

    async def test_returns_rendered_html(self, js_config, mock_server):
        """Response content is full HTML (not empty body)."""
        request = CrawlRequest(url=f"{mock_server}/page1", depth=0, priority=0)
        async with PlaywrightFetcher(js_config) as fetcher:
            response = await fetcher.fetch(request)
        assert response.status_code == 200
        assert response.content

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
    async def test_timeout_returns_error_response(self, mock_server):
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
