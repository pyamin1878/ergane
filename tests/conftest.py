"""Shared fixtures for Ergane tests."""

import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from ergane.models import CrawlConfig, CrawlRequest, CrawlResponse


@pytest.fixture
def config() -> CrawlConfig:
    """Default test configuration."""
    return CrawlConfig(
        max_requests_per_second=100.0,
        max_concurrent_requests=10,
        request_timeout=5.0,
        max_retries=1,
        batch_size=10,
        max_queue_size=100,
    )


@pytest.fixture
def sample_request() -> CrawlRequest:
    """Sample crawl request for testing."""
    return CrawlRequest(
        url="https://example.com/page",
        depth=0,
        priority=0,
    )


@pytest.fixture
def sample_html() -> str:
    """Sample HTML content for parser tests."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <style>.hidden { display: none; }</style>
        <script>console.log('test');</script>
    </head>
    <body>
        <h1>Welcome</h1>
        <p>This is a test paragraph.</p>
        <a href="/page1">Page 1</a>
        <a href="https://example.com/page2">Page 2</a>
        <a href="mailto:test@example.com">Email</a>
        <a href="#section">Anchor</a>
        <div class="content">
            <span class="item">Item 1</span>
            <span class="item">Item 2</span>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def malformed_html() -> str:
    """Malformed HTML for edge case testing."""
    return """
    <html>
    <head><title>Unclosed
    <body>
    <p>Missing closing tags
    <a href="relative">Link
    <div><span>Nested unclosed
    </html>
    """


@pytest.fixture
def sample_response(sample_request: CrawlRequest, sample_html: str) -> CrawlResponse:
    """Sample successful crawl response."""
    return CrawlResponse(
        url="https://example.com/page",
        status_code=200,
        content=sample_html,
        headers={"content-type": "text/html"},
        request=sample_request,
    )


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for pipeline output tests."""
    return tmp_path / "output"


@pytest.fixture
def temp_parquet_path(temp_output_dir: Path) -> Path:
    """Temporary parquet file path."""
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    return temp_output_dir / "test_output.parquet"


# ---------------------------------------------------------------------------
# Shared mock HTTP server
# ---------------------------------------------------------------------------

class MockHandler(BaseHTTPRequestHandler):
    """Flexible mock HTTP server handler for tests.

    Supports:
    - /get              → 200 JSON response
    - /delay/{seconds}  → Delayed response (for timeout testing)
    - /status/{code}    → Arbitrary status code
    - /robots.txt       → 404 (allow all)
    - /                 → Simple HTML page with links
    - /page1, /page2    → Simple HTML pages
    """

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/robots.txt":
            self.send_response(404)
            self.end_headers()
            return

        if path == "/get":
            body = '{"url": "/get", "method": "GET"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
            return

        # /delay/{n} — sleep then respond
        delay_match = re.match(r"^/delay/(\d+)$", path)
        if delay_match:
            seconds = int(delay_match.group(1))
            time.sleep(seconds)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"delayed")
            return

        # /status/{code} — return arbitrary status code
        status_match = re.match(r"^/status/(\d+)$", path)
        if status_match:
            code = int(status_match.group(1))
            self.send_response(code)
            self.end_headers()
            return

        # Static pages
        pages = {
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
                "</body></html>"
            ),
            "/page2": (
                "<html><head><title>Page 2</title></head><body>"
                "<h1>Page 2</h1>"
                "</body></html>"
            ),
        }

        body = pages.get(path)
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
def mock_server():
    """Start a mock HTTP server on a random port.

    Provides endpoints: /get, /delay/{n}, /status/{code}, /, /page1, /page2.
    """
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
