"""Integration tests for the full Crawler pipeline with a mock HTTP server."""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import polars as pl
import pytest

from src.main import Crawler
from src.models import CrawlConfig

# ---------------------------------------------------------------------------
# Lightweight mock HTTP server
# ---------------------------------------------------------------------------

PAGES = {
    "/": (
        "<html><head><title>Home</title></head><body>"
        "<h1>Home</h1>"
        '<a href="/page1">Page 1</a>'
        '<a href="/page2">Page 2</a>'
        "</body></html>"
    ),
    "/page1": (
        "<html><head><title>Page 1</title></head><body>"
        "<h1>Page 1</h1>"
        '<a href="/page3">Page 3</a>'
        "</body></html>"
    ),
    "/page2": (
        "<html><head><title>Page 2</title></head><body>"
        "<h1>Page 2</h1>"
        "</body></html>"
    ),
    "/page3": (
        "<html><head><title>Page 3</title></head><body>"
        "<h1>Page 3</h1>"
        "</body></html>"
    ),
}


class MockHandler(BaseHTTPRequestHandler):
    """Serves canned HTML pages for integration tests."""

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

    # Suppress request logging during tests
    def log_message(self, format, *args):
        pass


@pytest.fixture()
def mock_server():
    """Start a mock HTTP server on a random port."""
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestCrawlerIntegration:
    """End-to-end tests using a real HTTP server."""

    @pytest.mark.asyncio
    async def test_crawl_collects_pages(
        self, mock_server: str, tmp_path: Path
    ):
        """Crawler fetches pages and writes output."""
        output = tmp_path / "out.parquet"
        config = CrawlConfig(
            max_requests_per_second=100.0,
            max_concurrent_requests=4,
            request_timeout=5.0,
            max_retries=0,
            batch_size=10,
            respect_robots_txt=False,
        )
        crawler = Crawler(
            config=config,
            start_urls=[f"{mock_server}/"],
            output_path=str(output),
            max_pages=10,
            max_depth=2,
            same_domain=True,
            show_progress=False,
        )
        await crawler.run()

        assert output.exists()
        df = pl.read_parquet(output)
        # We have 4 pages reachable within depth 2
        assert len(df) == 4
        urls = set(df["url"].to_list())
        assert f"{mock_server}/" in urls
        assert f"{mock_server}/page1" in urls
        assert f"{mock_server}/page2" in urls
        assert f"{mock_server}/page3" in urls

    @pytest.mark.asyncio
    async def test_crawl_respects_max_pages(
        self, mock_server: str, tmp_path: Path
    ):
        """Crawler stops after max_pages is reached."""
        output = tmp_path / "out.parquet"
        config = CrawlConfig(
            max_requests_per_second=100.0,
            max_concurrent_requests=1,
            request_timeout=5.0,
            max_retries=0,
            batch_size=10,
            respect_robots_txt=False,
        )
        crawler = Crawler(
            config=config,
            start_urls=[f"{mock_server}/"],
            output_path=str(output),
            max_pages=2,
            max_depth=3,
            same_domain=True,
            show_progress=False,
        )
        await crawler.run()

        assert output.exists()
        df = pl.read_parquet(output)
        assert len(df) <= 2

    @pytest.mark.asyncio
    async def test_crawl_respects_max_depth(
        self, mock_server: str, tmp_path: Path
    ):
        """Crawler does not follow links beyond max_depth."""
        output = tmp_path / "out.parquet"
        config = CrawlConfig(
            max_requests_per_second=100.0,
            max_concurrent_requests=1,
            request_timeout=5.0,
            max_retries=0,
            batch_size=10,
            respect_robots_txt=False,
        )
        crawler = Crawler(
            config=config,
            start_urls=[f"{mock_server}/"],
            output_path=str(output),
            max_pages=10,
            max_depth=0,
            same_domain=True,
            show_progress=False,
        )
        await crawler.run()

        assert output.exists()
        df = pl.read_parquet(output)
        # depth=0 means only the seed URL is crawled
        assert len(df) == 1


class TestGracefulShutdown:
    """Tests for graceful shutdown via the _shutdown event."""

    @pytest.mark.asyncio
    async def test_shutdown_event_stops_crawler(
        self, mock_server: str, tmp_path: Path
    ):
        """Setting _shutdown event causes crawler to stop early."""
        output = tmp_path / "out.parquet"
        config = CrawlConfig(
            max_requests_per_second=100.0,
            max_concurrent_requests=1,
            request_timeout=5.0,
            max_retries=0,
            batch_size=10,
            respect_robots_txt=False,
        )
        crawler = Crawler(
            config=config,
            start_urls=[f"{mock_server}/"],
            output_path=str(output),
            max_pages=1000,
            max_depth=10,
            same_domain=True,
            show_progress=False,
        )

        # Schedule shutdown after a short delay
        async def trigger_shutdown():
            await asyncio.sleep(0.3)
            crawler._shutdown.set()

        shutdown_task = asyncio.create_task(trigger_shutdown())
        await crawler.run()
        await shutdown_task

        # Crawler should have stopped well before 1000 pages
        assert crawler._pages_crawled < 1000

    @pytest.mark.asyncio
    async def test_shutdown_flushes_data(
        self, mock_server: str, tmp_path: Path
    ):
        """Data collected before shutdown is still written to disk."""
        output = tmp_path / "out.parquet"
        config = CrawlConfig(
            max_requests_per_second=100.0,
            max_concurrent_requests=1,
            request_timeout=5.0,
            max_retries=0,
            batch_size=10,
            respect_robots_txt=False,
        )
        crawler = Crawler(
            config=config,
            start_urls=[f"{mock_server}/"],
            output_path=str(output),
            max_pages=1000,
            max_depth=10,
            same_domain=True,
            show_progress=False,
        )

        async def trigger_shutdown():
            await asyncio.sleep(0.5)
            crawler._shutdown.set()

        shutdown_task = asyncio.create_task(trigger_shutdown())
        await crawler.run()
        await shutdown_task

        # Output should exist with whatever was collected
        assert output.exists()
        df = pl.read_parquet(output)
        assert len(df) >= 1


class TestDeduplicationOnConsolidate:
    """Tests that consolidation deduplicates by URL."""

    @pytest.mark.asyncio
    async def test_consolidate_removes_duplicate_urls(
        self, tmp_path: Path
    ):
        """Duplicate URLs across batches are removed during consolidation."""
        from src.crawler import Pipeline

        output = tmp_path / "dedup.parquet"
        config = CrawlConfig(batch_size=2)
        pipeline = Pipeline(config, output)

        from tests.test_pipeline import make_item

        # Batch 1: urls A and B
        await pipeline.add(make_item("https://example.com/a", "A-v1"))
        await pipeline.add(make_item("https://example.com/b", "B-v1"))
        # Batch 2: url A again (updated) and C
        await pipeline.add(make_item("https://example.com/a", "A-v2"))
        await pipeline.add(make_item("https://example.com/c", "C-v1"))
        await pipeline.flush()

        assert len(pipeline.get_batch_files()) == 2

        pipeline.consolidate()
        df = pl.read_parquet(output)
        assert len(df) == 3  # A, B, C — not 4

        # The kept row for /a should be the last occurrence
        row_a = df.filter(
            pl.col("url") == "https://example.com/a"
        )
        assert len(row_a) == 1
        assert row_a[0, "title"] == "A-v2"
