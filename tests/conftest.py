"""Shared fixtures for Arachne tests."""
import pytest
import tempfile
from pathlib import Path

from src.models import CrawlConfig, CrawlRequest, CrawlResponse, ParsedItem


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
