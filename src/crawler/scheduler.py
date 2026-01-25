import asyncio
import heapq
from urllib.parse import urlparse

from src.models import CrawlConfig, CrawlRequest


class Scheduler:
    """URL frontier with deduplication and priority queue support."""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self._queue: list[tuple[int, int, CrawlRequest]] = []
        self._counter = 0
        self._seen: set[str] = set()
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized.rstrip("/").lower()

    async def add(self, request: CrawlRequest) -> bool:
        """Add a URL to the queue if not seen before.

        Returns True if added, False if duplicate or queue full.
        """
        normalized = self._normalize_url(request.url)

        async with self._lock:
            if normalized in self._seen:
                return False

            if len(self._queue) >= self.config.max_queue_size:
                return False

            self._seen.add(normalized)
            self._counter += 1
            heapq.heappush(
                self._queue,
                (-request.priority, self._counter, request),
            )
            self._not_empty.set()
            return True

    async def add_many(self, requests: list[CrawlRequest]) -> int:
        """Add multiple URLs, returns count of URLs actually added."""
        added = 0
        for req in requests:
            if await self.add(req):
                added += 1
        return added

    async def get(self) -> CrawlRequest:
        """Get the next URL from the queue, waiting if empty."""
        while True:
            async with self._lock:
                if self._queue:
                    _, _, request = heapq.heappop(self._queue)
                    if not self._queue:
                        self._not_empty.clear()
                    return request

            await self._not_empty.wait()

    async def get_nowait(self) -> CrawlRequest | None:
        """Get next URL without waiting, returns None if empty."""
        async with self._lock:
            if self._queue:
                _, _, request = heapq.heappop(self._queue)
                if not self._queue:
                    self._not_empty.clear()
                return request
            return None

    async def size(self) -> int:
        """Return current queue size."""
        async with self._lock:
            return len(self._queue)

    async def seen_count(self) -> int:
        """Return total URLs seen (including processed)."""
        async with self._lock:
            return len(self._seen)

    async def is_empty(self) -> bool:
        """Check if queue is empty."""
        async with self._lock:
            return len(self._queue) == 0

    def mark_seen(self, url: str) -> None:
        """Mark a URL as seen without adding to queue."""
        normalized = self._normalize_url(url)
        self._seen.add(normalized)
