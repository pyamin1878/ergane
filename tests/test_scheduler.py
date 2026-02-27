"""Tests for the URL scheduler with deduplication and priority queue."""

import asyncio

import pytest

from ergane.crawler import Scheduler
from ergane.models import CrawlConfig, CrawlRequest


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
    async def test_reordered_query_params_deduplicated(self, scheduler: Scheduler):
        """Test that URLs with reordered query params are deduplicated."""
        await scheduler.add(CrawlRequest(url="https://example.com/search?a=1&b=2"))
        result = await scheduler.add(
            CrawlRequest(url="https://example.com/search?b=2&a=1")
        )
        assert result is False
        assert await scheduler.size() == 1

    @pytest.mark.asyncio
    async def test_different_urls_accepted(self, scheduler: Scheduler):
        """Test that different URLs are accepted."""
        await scheduler.add(CrawlRequest(url="https://example.com/page1"))
        result = await scheduler.add(CrawlRequest(url="https://example.com/page2"))
        assert result is True
        assert await scheduler.size() == 2

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
        requests = [CrawlRequest(url=f"https://example.com/{i}") for i in range(5)]
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


class TestAddManyBatching:
    """add_many correctness and dedup behaviour."""

    async def test_add_many_deduplicates_within_batch(self, scheduler: Scheduler):
        """Duplicates within the same add_many call are rejected."""
        requests = [
            CrawlRequest(url="https://example.com/a"),
            CrawlRequest(url="https://example.com/a"),  # duplicate
            CrawlRequest(url="https://example.com/b"),
        ]
        added = await scheduler.add_many(requests)
        assert added == 2
        assert await scheduler.size() == 2

    async def test_add_many_deduplicates_against_seen(self, scheduler: Scheduler):
        """URLs already seen via add() are rejected by add_many."""
        await scheduler.add(CrawlRequest(url="https://example.com/a"))
        added = await scheduler.add_many([
            CrawlRequest(url="https://example.com/a"),  # already seen
            CrawlRequest(url="https://example.com/b"),
        ])
        assert added == 1
        assert await scheduler.size() == 2  # original + new

    async def test_add_many_returns_count(self, scheduler: Scheduler):
        """add_many returns number of URLs actually enqueued."""
        requests = [CrawlRequest(url=f"https://example.com/{i}") for i in range(5)]
        added = await scheduler.add_many(requests)
        assert added == 5


class TestWaitNotEmpty:
    """Scheduler.wait_not_empty wakes workers when URLs arrive."""

    async def test_wait_not_empty_resolves_when_url_added(self, scheduler: Scheduler):
        """wait_not_empty() returns once a URL is enqueued."""
        async def _add_later():
            await asyncio.sleep(0.05)
            await scheduler.add(CrawlRequest(url="https://example.com/wake"))

        asyncio.create_task(_add_later())
        # Should return within ~0.1s once the URL is added
        await asyncio.wait_for(scheduler.wait_not_empty(), timeout=1.0)
        assert await scheduler.size() == 1

    async def test_wait_not_empty_immediate_if_already_has_items(
        self, scheduler: Scheduler
    ):
        """wait_not_empty() returns immediately when queue is non-empty."""
        await scheduler.add(CrawlRequest(url="https://example.com/1"))
        # Should not block at all
        await asyncio.wait_for(scheduler.wait_not_empty(), timeout=0.1)
