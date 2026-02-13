"""Tests for the programmatic Crawler engine API."""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import polars as pl
import pytest

from ergane.crawler.engine import Crawler, crawl
from ergane.crawler.hooks import BaseHook

# ---------------------------------------------------------------------------
# Mock server for engine tests
# ---------------------------------------------------------------------------

PAGES = {
    "/": (
        "<html><head><title>Home</title></head><body>"
        "<h1>Home</h1>"
        '<a href="/page1">Page 1</a>'
        "</body></html>"
    ),
    "/page1": (
        "<html><head><title>Page 1</title></head><body>"
        "<h1>Page 1</h1>"
        "</body></html>"
    ),
}


class _MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/robots.txt":
            self.send_response(404)
            self.end_headers()
            return
        body = PAGES.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format, *args):
        pass


@pytest.fixture()
def engine_server():
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Context manager & lifecycle
# ---------------------------------------------------------------------------

class TestCrawlerContextManager:
    """Basic lifecycle tests."""

    @pytest.mark.asyncio
    async def test_run_returns_results(self, engine_server: str):
        """run() returns a list of extracted items."""
        async with Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
        ) as c:
            results = await c.run()

        assert len(results) == 2  # Home + Page 1
        urls = {getattr(r, "url", None) for r in results}
        assert f"{engine_server}/" in urls
        assert f"{engine_server}/page1" in urls

    @pytest.mark.asyncio
    async def test_run_without_context_manager(self, engine_server: str):
        """Crawler works even without explicit context manager."""
        c = Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
        )
        results = await c.run()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_run_with_output(self, engine_server: str, tmp_path: Path):
        """run() writes output to disk when output= is set."""
        output = tmp_path / "results.parquet"
        async with Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
            output=str(output),
        ) as c:
            results = await c.run()

        assert output.exists()
        df = pl.read_parquet(output)
        assert len(df) == len(results)

    @pytest.mark.asyncio
    async def test_stream_yields_items(self, engine_server: str):
        """stream() yields items as they arrive."""
        items = []
        async with Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
        ) as c:
            async for item in c.stream():
                items.append(item)

        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_pages_crawled_property(self, engine_server: str):
        """pages_crawled reflects the number of pages fetched."""
        async with Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
        ) as c:
            await c.run()
            assert c.pages_crawled == 2


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

class TestCrawlFunction:
    """Tests for the crawl() convenience function."""

    @pytest.mark.asyncio
    async def test_crawl_returns_results(self, engine_server: str):
        results = await crawl(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
        )
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Hooks integration
# ---------------------------------------------------------------------------

class TestCrawlerWithHooks:
    """Tests that hooks are invoked during the crawl."""

    @pytest.mark.asyncio
    async def test_hooks_invoked(self, engine_server: str):
        """Hooks see requests and responses."""
        seen_requests = []
        seen_responses = []

        class RecordingHook(BaseHook):
            async def on_request(self, request):
                seen_requests.append(request.url)
                return request

            async def on_response(self, response):
                seen_responses.append(response.url)
                return response

        async with Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
            hooks=[RecordingHook()],
        ) as c:
            await c.run()

        assert len(seen_requests) >= 1
        assert len(seen_responses) >= 1

    @pytest.mark.asyncio
    async def test_on_request_skip(self, engine_server: str):
        """Returning None from on_request skips that URL."""

        class SkipAllHook(BaseHook):
            async def on_request(self, request):
                return None  # skip everything

        async with Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
            hooks=[SkipAllHook()],
        ) as c:
            results = await c.run()

        # Nothing should be extracted since all requests are skipped
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_on_response_discard(self, engine_server: str):
        """Returning None from on_response discards the response."""

        class DiscardAllHook(BaseHook):
            async def on_request(self, request):
                return request

            async def on_response(self, response):
                return None  # discard everything

        async with Crawler(
            urls=[f"{engine_server}/"],
            max_pages=5,
            max_depth=1,
            rate_limit=100.0,
            respect_robots_txt=False,
            hooks=[DiscardAllHook()],
        ) as c:
            results = await c.run()

        # Pages are fetched but responses discarded — no extracted items
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestCrawlerShutdown:
    """Tests for graceful shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_returns_partial_results(self, engine_server: str):
        """shutdown() stops crawling and returns what was collected so far."""
        crawler = Crawler(
            urls=[f"{engine_server}/"],
            max_pages=1000,
            max_depth=10,
            rate_limit=100.0,
            respect_robots_txt=False,
        )

        async with crawler:
            async def trigger_shutdown():
                await asyncio.sleep(0.3)
                crawler.shutdown()

            shutdown_task = asyncio.create_task(trigger_shutdown())
            results = await crawler.run()
            await shutdown_task

        assert crawler.pages_crawled < 1000
        assert len(results) >= 1
