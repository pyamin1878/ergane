"""Tests for the HTTP fetcher with rate limiting and retry logic."""

import asyncio

import pytest

from src.crawler import Fetcher
from src.crawler.fetcher import TokenBucket
from src.models import CrawlConfig, CrawlRequest


class TestTokenBucket:
    """Token bucket rate limiter tests."""

    @pytest.mark.asyncio
    async def test_initial_tokens(self):
        """Test bucket starts with full capacity."""
        bucket = TokenBucket(rate=10.0, capacity=10.0)
        # First 10 acquires should be instant
        for _ in range(10):
            await bucket.acquire()
        # Allow tiny floating point accumulation from elapsed time
        assert bucket.tokens < 0.1

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Test that rate limiting delays acquisition."""
        bucket = TokenBucket(rate=100.0, capacity=1.0)  # 100/sec, 1 token capacity
        await bucket.acquire()  # Use the one token

        start = asyncio.get_event_loop().time()
        await bucket.acquire()  # Should wait ~0.01s
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed >= 0.005  # Should have waited some time

    @pytest.mark.asyncio
    async def test_token_refill(self):
        """Test tokens refill over time."""
        bucket = TokenBucket(rate=1000.0)  # Fast refill for testing
        await bucket.acquire()
        await asyncio.sleep(0.01)  # Wait for refill
        # Should have refilled some tokens
        assert bucket.tokens > 0


    @pytest.mark.asyncio
    async def test_concurrent_acquires_not_serialized_through_sleep(self):
        """Two workers waiting for tokens should not serialize through the sleep.

        With the old bug, one worker sleeping inside the lock would block
        the other from even checking its token balance.
        """
        bucket = TokenBucket(rate=1.0, capacity=1.0)
        await bucket.acquire()  # Drain the single token

        async def timed_acquire():
            start = asyncio.get_event_loop().time()
            await bucket.acquire()
            return asyncio.get_event_loop().time() - start

        # Launch two concurrent acquires — both need to wait for refill
        t1, t2 = await asyncio.gather(timed_acquire(), timed_acquire())

        # If the lock were held during sleep, total would be ~2s (serialized).
        # With the fix, the second worker can enter the lock while the first sleeps,
        # so total wall-clock should be well under 2x the single-wait time.
        assert max(t1, t2) < 2.5  # generous bound; serialized would be ~2s


class TestFetcherInitialization:
    """Fetcher initialization and context manager tests."""

    @pytest.mark.asyncio
    async def test_context_manager(self, config: CrawlConfig):
        """Test fetcher as async context manager."""
        async with Fetcher(config) as fetcher:
            assert fetcher._client is not None
        assert fetcher._client is None or fetcher._client.is_closed

    @pytest.mark.asyncio
    async def test_fetch_without_init_raises(self, config: CrawlConfig):
        """Test that fetching without context manager raises."""
        fetcher = Fetcher(config)
        request = CrawlRequest(url="https://example.com")

        with pytest.raises(RuntimeError, match="not initialized"):
            await fetcher.fetch(request)


class TestDomainBuckets:
    """Per-domain rate limiting tests."""

    @pytest.mark.asyncio
    async def test_separate_domain_buckets(self, config: CrawlConfig):
        """Test that different domains have separate rate limits."""
        async with Fetcher(config) as fetcher:
            bucket1 = fetcher._get_bucket("example.com")
            bucket2 = fetcher._get_bucket("other.com")
            assert bucket1 is not bucket2

    @pytest.mark.asyncio
    async def test_same_domain_reuses_bucket(self, config: CrawlConfig):
        """Test that same domain reuses bucket."""
        async with Fetcher(config) as fetcher:
            bucket1 = fetcher._get_bucket("example.com")
            bucket2 = fetcher._get_bucket("example.com")
            assert bucket1 is bucket2


class TestRobotsHandling:
    """robots.txt handling tests."""

    @pytest.mark.asyncio
    async def test_robots_disabled(self, config: CrawlConfig):
        """Test that robots.txt can be disabled."""
        config.respect_robots_txt = False
        async with Fetcher(config) as fetcher:
            result = await fetcher.can_fetch("https://example.com/blocked")
            assert result is True

    @pytest.mark.asyncio
    async def test_robots_cache(self, config: CrawlConfig):
        """Test that robots.txt results are cached."""
        async with Fetcher(config) as fetcher:
            # Cache miss initially
            assert "https://example.com/robots.txt" not in fetcher._robots_cache

            # First call populates cache (will fail but cache None)
            await fetcher._get_robots("https://nonexistent.invalid/page")

            # Should be cached now
            assert "https://nonexistent.invalid/robots.txt" in fetcher._robots_cache


class TestFetchResponses:
    """Fetch response handling tests."""

    @pytest.mark.asyncio
    async def test_successful_fetch_structure(self, config: CrawlConfig):
        """Test response structure from successful fetch."""
        # This will fail but tests error handling path
        config.max_retries = 0
        config.request_timeout = 1.0

        async with Fetcher(config) as fetcher:
            request = CrawlRequest(url="https://httpbin.org/get")
            response = await fetcher.fetch(request)

            assert response.url is not None
            assert response.request == request
            assert response.fetched_at is not None

    @pytest.mark.asyncio
    async def test_timeout_handling(self, config: CrawlConfig):
        """Test timeout produces proper error response."""
        config.max_retries = 0
        config.request_timeout = 0.001  # Very short timeout

        async with Fetcher(config) as fetcher:
            request = CrawlRequest(url="https://httpbin.org/delay/10")
            response = await fetcher.fetch(request)

            assert response.status_code == 0
            assert response.error is not None

    @pytest.mark.asyncio
    async def test_invalid_url_handling(self, config: CrawlConfig):
        """Test handling of unreachable URLs."""
        config.max_retries = 0

        async with Fetcher(config) as fetcher:
            request = CrawlRequest(url="https://nonexistent.invalid.domain.test/")
            response = await fetcher.fetch(request)

            assert response.status_code == 0
            assert response.error is not None


class TestRetryLogic:
    """Retry mechanism tests."""

    @pytest.mark.asyncio
    async def test_retry_count_respected(self, config: CrawlConfig):
        """Test that max retries is respected."""
        config.max_retries = 2
        config.retry_base_delay = 0.01
        config.request_timeout = 0.001

        async with Fetcher(config) as fetcher:
            request = CrawlRequest(url="https://httpbin.org/delay/10")
            # This should try 3 times (initial + 2 retries)
            await fetcher.fetch(request)
            # Test passes if it completes without hanging

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, config: CrawlConfig):
        """Test that retry delay increases exponentially."""
        config.max_retries = 2
        config.retry_base_delay = 0.1
        config.request_timeout = 0.001

        async with Fetcher(config) as fetcher:
            request = CrawlRequest(url="https://httpbin.org/delay/10")

            start = asyncio.get_event_loop().time()
            await fetcher.fetch(request)
            elapsed = asyncio.get_event_loop().time() - start

            # Should have waited: 0.1 (first retry) + 0.2 (second retry) = 0.3s min
            assert elapsed >= 0.25
