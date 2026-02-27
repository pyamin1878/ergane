import asyncio
import heapq
from collections import Counter
from urllib.parse import parse_qsl, urlencode, urlparse

from ergane.logging import get_logger
from ergane.models import CrawlConfig, CrawlRequest

_logger = get_logger()


def _request_to_dict(request: CrawlRequest) -> dict:
    """Convert CrawlRequest to dict for serialization."""
    return {
        "url": request.url,
        "depth": request.depth,
        "priority": request.priority,
        "metadata": request.metadata,
    }


# Maximum number of normalized URLs to track in the seen-set.
# Uses an insertion-ordered dict so the oldest entries can be evicted
# when the limit is reached, keeping memory bounded for long crawls.
_MAX_SEEN_URLS = 100_000
_EVICT_BATCH = _MAX_SEEN_URLS // 10  # evict 10 % at a time


class Scheduler:
    """URL frontier with deduplication and priority queue support."""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self._queue: list[tuple[int, int, CrawlRequest]] = []
        self._counter = 0
        # Ordered dict used as a bounded insertion-order set.
        # Ordering allows O(1) eviction of the oldest entries.
        self._seen: dict[str, None] = {}
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            sorted_query = urlencode(sorted(parse_qsl(parsed.query)))
            normalized += f"?{sorted_query}"
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
                _logger.warning(
                    "Queue full (%d), dropping URL: %s",
                    self.config.max_queue_size,
                    request.url,
                )
                return False

            # Evict oldest entries when the seen-set is full to keep memory
            # bounded on very long crawls.  Evicted URLs may be re-crawled
            # if encountered again, but this is the correct tradeoff versus
            # an unbounded set that grows without limit.
            if len(self._seen) >= _MAX_SEEN_URLS:
                evict_keys = list(self._seen.keys())[:_EVICT_BATCH]
                domain_counts = Counter(urlparse(k).netloc for k in evict_keys)
                top_domains_str = ", ".join(
                    f"{d}({c})" for d, c in domain_counts.most_common(3)
                )
                for k in evict_keys:
                    del self._seen[k]
                _logger.warning(
                    "URL seen-set capped at %d; evicted %d oldest entries "
                    "(top domains in evicted batch: %s)",
                    _MAX_SEEN_URLS,
                    _EVICT_BATCH,
                    top_domains_str,
                )

            self._seen[normalized] = None
            self._counter += 1
            heapq.heappush(
                self._queue,
                (-request.priority, self._counter, request),
            )
            self._not_empty.set()
            return True

    async def add_many(self, requests: list[CrawlRequest]) -> int:
        """Add multiple URLs atomically under a single lock acquisition."""
        added = 0
        notify = False
        async with self._lock:
            for req in requests:
                normalized = self._normalize_url(req.url)
                if normalized in self._seen:
                    continue
                if len(self._queue) >= self.config.max_queue_size:
                    _logger.warning(
                        "Queue full (%d), dropping URL: %s",
                        self.config.max_queue_size,
                        req.url,
                    )
                    continue
                if len(self._seen) >= _MAX_SEEN_URLS:
                    evict_keys = list(self._seen.keys())[:_EVICT_BATCH]
                    domain_counts = Counter(urlparse(k).netloc for k in evict_keys)
                    top_domains_str = ", ".join(
                        f"{d}({c})" for d, c in domain_counts.most_common(3)
                    )
                    for k in evict_keys:
                        del self._seen[k]
                    _logger.warning(
                        "URL seen-set capped at %d; evicted %d oldest entries "
                        "(top domains in evicted batch: %s)",
                        _MAX_SEEN_URLS,
                        _EVICT_BATCH,
                        top_domains_str,
                    )
                self._seen[normalized] = None
                self._counter += 1
                heapq.heappush(
                    self._queue,
                    (-req.priority, self._counter, req),
                )
                added += 1
                notify = True
        if notify:
            self._not_empty.set()
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

    async def wait_not_empty(self) -> None:
        """Wait until at least one URL is in the queue.

        Returns immediately if the queue already has items. Intended for
        workers to replace ``asyncio.sleep(0.1)`` with an event-driven wait.
        """
        await self._not_empty.wait()

    def get_state(self) -> dict:
        """Export scheduler state for checkpointing.

        Returns:
            Dictionary with seen_urls and queue data.
        """
        return {
            "seen_urls": list(self._seen),
            "queue": [
                (p, c, _request_to_dict(r)) for p, c, r in self._queue
            ],
        }

    def restore_state(self, state: dict) -> None:
        """Restore scheduler state from checkpoint.

        Args:
            state: Dictionary with seen_urls and queue data.
        """
        self._seen = {url: None for url in state["seen_urls"]}
        self._queue = [
            (p, c, CrawlRequest(**r)) for p, c, r in state["queue"]
        ]
        # Update counter to avoid duplicates
        if self._queue:
            self._counter = max(c for _, c, _ in self._queue) + 1
        if self._queue:
            self._not_empty.set()
