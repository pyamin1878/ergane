"""Tests for the URL scheduler with deduplication and priority queue."""
import pytest
import asyncio

from src.models import CrawlConfig, CrawlRequest
from src.crawler import Scheduler


@pytest.fixture
def scheduler(config: CrawlConfig) -> Scheduler:
    """Create a scheduler instance for testing."""
    return Scheduler(config)


class TestSchedulerBasics:
    """Basic scheduler functionality tests."""

    @pytest.mark.asyncio
    async def test_add_and_get(self, scheduler: Scheduler):
        """Test adding and retrieving a URL."""
        request = CrawlRequest(url="https://example.com/")
        added = await scheduler.add(request)
        assert added is True

        retrieved = await scheduler.get()
        assert retrieved.url == "https://example.com/"

    @pytest.mark.asyncio
    async def test_empty_queue_get_nowait(self, scheduler: Scheduler):
        """Test get_nowait on empty queue returns None."""
        result = await scheduler.get_nowait()
        assert result is None

    @pytest.mark.asyncio
    async def test_queue_size(self, scheduler: Scheduler):
        """Test queue size tracking."""
        assert await scheduler.size() == 0
        assert await scheduler.is_empty() is True

        await scheduler.add(CrawlRequest(url="https://example.com/1"))
        assert await scheduler.size() == 1
        assert await scheduler.is_empty() is False

        await scheduler.add(CrawlRequest(url="https://example.com/2"))
        assert await scheduler.size() == 2


class TestDeduplication:
    """URL deduplication tests."""

    @pytest.mark.asyncio
    async def test_exact_duplicate_rejected(self, scheduler: Scheduler):
        """Test that exact duplicates are rejected."""
        request = CrawlRequest(url="https://example.com/page")
        assert await scheduler.add(request) is True
        assert await scheduler.add(request) is False
        assert await scheduler.size() == 1

    @pytest.mark.asyncio
    async def test_normalized_duplicate_rejected(self, scheduler: Scheduler):
        """Test that normalized duplicates are rejected."""
        await scheduler.add(CrawlRequest(url="https://example.com/page/"))
        # Same URL without trailing slash should be deduplicated
        result = await scheduler.add(CrawlRequest(url="https://example.com/page"))
        assert result is False

    @pytest.mark.asyncio
    async def test_case_normalization(self, scheduler: Scheduler):
        """Test that URL case is normalized."""
        await scheduler.add(CrawlRequest(url="https://Example.COM/Page"))
        result = await scheduler.add(CrawlRequest(url="https://example.com/page"))
        assert result is False

    @pytest.mark.asyncio
    async def test_different_urls_accepted(self, scheduler: Scheduler):
        """Test that different URLs are accepted."""
        await scheduler.add(CrawlRequest(url="https://example.com/page1"))
        result = await scheduler.add(CrawlRequest(url="https://example.com/page2"))
        assert result is True
        assert await scheduler.size() == 2

    @pytest.mark.asyncio
    async def test_mark_seen(self, scheduler: Scheduler):
        """Test marking URL as seen without adding to queue."""
        scheduler.mark_seen("https://example.com/seen")
        result = await scheduler.add(CrawlRequest(url="https://example.com/seen"))
        assert result is False
        assert await scheduler.size() == 0

    @pytest.mark.asyncio
    async def test_seen_count(self, scheduler: Scheduler):
        """Test seen count tracking."""
        await scheduler.add(CrawlRequest(url="https://example.com/1"))
        await scheduler.add(CrawlRequest(url="https://example.com/2"))
        await scheduler.add(CrawlRequest(url="https://example.com/2"))  # duplicate

        assert await scheduler.seen_count() == 2


class TestPriorityQueue:
    """Priority queue behavior tests."""

    @pytest.mark.asyncio
    async def test_higher_priority_first(self, scheduler: Scheduler):
        """Test that higher priority URLs are returned first."""
        await scheduler.add(CrawlRequest(url="https://example.com/low", priority=0))
        await scheduler.add(CrawlRequest(url="https://example.com/high", priority=10))
        await scheduler.add(CrawlRequest(url="https://example.com/medium", priority=5))

        first = await scheduler.get()
        assert first.url == "https://example.com/high"

        second = await scheduler.get()
        assert second.url == "https://example.com/medium"

        third = await scheduler.get()
        assert third.url == "https://example.com/low"

    @pytest.mark.asyncio
    async def test_fifo_same_priority(self, scheduler: Scheduler):
        """Test FIFO order for same priority."""
        await scheduler.add(CrawlRequest(url="https://example.com/1", priority=0))
        await scheduler.add(CrawlRequest(url="https://example.com/2", priority=0))
        await scheduler.add(CrawlRequest(url="https://example.com/3", priority=0))

        first = await scheduler.get()
        assert first.url == "https://example.com/1"

        second = await scheduler.get()
        assert second.url == "https://example.com/2"


class TestConcurrency:
    """Concurrency and capacity tests."""

    @pytest.mark.asyncio
    async def test_queue_capacity(self, config: CrawlConfig):
        """Test queue respects max size."""
        config.max_queue_size = 3
        scheduler = Scheduler(config)

        assert await scheduler.add(CrawlRequest(url="https://example.com/1")) is True
        assert await scheduler.add(CrawlRequest(url="https://example.com/2")) is True
        assert await scheduler.add(CrawlRequest(url="https://example.com/3")) is True
        assert await scheduler.add(CrawlRequest(url="https://example.com/4")) is False

    @pytest.mark.asyncio
    async def test_add_many(self, scheduler: Scheduler):
        """Test adding multiple URLs at once."""
        requests = [
            CrawlRequest(url=f"https://example.com/{i}")
            for i in range(5)
        ]
        added = await scheduler.add_many(requests)
        assert added == 5
        assert await scheduler.size() == 5

    @pytest.mark.asyncio
    async def test_add_many_with_duplicates(self, scheduler: Scheduler):
        """Test add_many filters duplicates."""
        requests = [
            CrawlRequest(url="https://example.com/1"),
            CrawlRequest(url="https://example.com/2"),
            CrawlRequest(url="https://example.com/1"),  # duplicate
        ]
        added = await scheduler.add_many(requests)
        assert added == 2

    @pytest.mark.asyncio
    async def test_concurrent_adds(self, scheduler: Scheduler):
        """Test thread safety of concurrent adds."""
        async def add_urls(start: int, count: int):
            for i in range(count):
                await scheduler.add(
                    CrawlRequest(url=f"https://example.com/{start + i}")
                )

        # Add URLs concurrently from multiple tasks
        await asyncio.gather(
            add_urls(0, 10),
            add_urls(10, 10),
            add_urls(20, 10),
        )

        assert await scheduler.size() == 30
