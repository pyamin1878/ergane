"""Crawl engine — pure async orchestration with no presentation concerns.

This module provides the programmatic API for ergane:

    async with Crawler(urls=["https://example.com"], max_pages=10) as c:
        results = await c.run()

    # or stream incrementally:
    async with Crawler(urls=["https://example.com"]) as c:
        async for item in c.stream():
            print(item)

    # one-shot convenience:
    results = await crawl(urls=["https://example.com"], max_pages=10)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from ergane.crawler.checkpoint import (
    CrawlerCheckpoint,
    create_checkpoint,
    delete_checkpoint,
    save_checkpoint,
)
from ergane.crawler.fetcher import Fetcher
from ergane.crawler.hooks import CrawlHook
from ergane.crawler.parser import extract_data, extract_links, extract_typed_data
from ergane.crawler.pipeline import OutputFormat, Pipeline
from ergane.crawler.scheduler import Scheduler
from ergane.logging import get_logger
from ergane.models import CrawlConfig, CrawlRequest, CrawlResponse
from ergane.schema import ExtractionError

_logger = get_logger()


class Crawler:
    """Orchestrates the crawl pipeline with hooks.

    Flow: scheduler -> hooks -> fetcher -> hooks -> parser -> pipeline.

    Can be used as an async context manager (manages Fetcher lifecycle) or
    manually with explicit ``shutdown()`` calls.
    """

    def __init__(
        self,
        urls: list[str],
        *,
        schema: type[BaseModel] | None = None,
        concurrency: int = 10,
        max_pages: int = 100,
        max_depth: int = 3,
        rate_limit: float = 10.0,
        timeout: float = 30.0,
        same_domain: bool = True,
        respect_robots_txt: bool = True,
        user_agent: str | None = None,
        proxy: str | None = None,
        hooks: list[CrawlHook] | None = None,
        output: str | Path | None = None,
        output_format: OutputFormat = "auto",
        cache: bool = False,
        cache_dir: Path = Path(".ergane_cache"),
        cache_ttl: int = 3600,
        checkpoint_interval: int = 0,
        checkpoint_path: str | Path | None = None,
        resume_from: CrawlerCheckpoint | None = None,
        config: CrawlConfig | None = None,
    ) -> None:
        # Build CrawlConfig from kwargs or use provided one
        if config is not None:
            self._config = config
        else:
            cfg_kwargs: dict = {
                "max_requests_per_second": rate_limit,
                "max_concurrent_requests": concurrency,
                "request_timeout": timeout,
                "respect_robots_txt": respect_robots_txt,
                "output_schema": schema,
                "proxy": proxy,
                "cache_enabled": cache,
                "cache_dir": cache_dir,
                "cache_ttl": cache_ttl,
            }
            if user_agent is not None:
                cfg_kwargs["user_agent"] = user_agent
            self._config = CrawlConfig(**cfg_kwargs)

        self._start_urls = urls
        self._schema = schema or self._config.output_schema
        self._max_pages = max_pages
        self._max_depth = max_depth
        self._same_domain = same_domain
        self._hooks: list[CrawlHook] = hooks or []
        self._output = Path(output) if output else None
        self._output_format = output_format

        self._allowed_domains: set[str] = set()
        self._shutdown_event = asyncio.Event()
        self._pages_crawled = 0
        self._active_tasks = 0
        self._counter_lock = asyncio.Lock()
        self._batch_number = 0

        # Checkpoint support
        self._checkpoint_interval = checkpoint_interval
        self._checkpoint_path = (
            Path(checkpoint_path) if checkpoint_path else None
        )
        self._resume_from = resume_from

        self._stats: dict[str, int] = {
            "pages_crawled": 0,
            "items_extracted": 0,
            "errors": 0,
            "cache_hits": 0,
        }
        self._start_time: float = 0.0

        self._fetcher: Fetcher | None = None
        self._owns_fetcher = False

    @property
    def config(self) -> CrawlConfig:
        return self._config

    @property
    def pages_crawled(self) -> int:
        return self._pages_crawled

    @property
    def stats(self) -> dict:
        """Return a snapshot of crawl statistics.

        Keys: pages_crawled, items_extracted, errors, cache_hits,
              pages_per_sec (derived), elapsed (derived, seconds).
        """
        import time

        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
        # Copy stats dict under lock to avoid torn reads across multiple fields.
        # asyncio is cooperative so this is safe from a yield-in-between perspective,
        # but an explicit snapshot makes the intent clear and future-proofs against
        # thread-based executors.
        stats_snapshot = dict(self._stats)
        return {
            **stats_snapshot,
            "elapsed": elapsed,
            "pages_per_sec": stats_snapshot["pages_crawled"] / max(elapsed, 0.1),
        }

    # -- Context manager --------------------------------------------------

    async def __aenter__(self) -> Crawler:
        self._fetcher = Fetcher(self._config)
        await self._fetcher.__aenter__()
        self._owns_fetcher = True
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_fetcher and self._fetcher is not None:
            await self._fetcher.__aexit__(*exc)
            self._fetcher = None

    # -- Public API -------------------------------------------------------

    async def run(self) -> list[BaseModel]:
        """Execute the crawl and return all extracted items."""
        results: list[BaseModel] = []
        async for item in self._crawl_iter():
            results.append(item)
        return results

    async def stream(self) -> AsyncIterator[BaseModel]:
        """Yield items as they are extracted. Memory-efficient for large crawls."""
        async for item in self._crawl_iter():
            yield item

    def shutdown(self) -> None:
        """Signal the crawler to stop gracefully."""
        self._shutdown_event.set()

    # -- Internal ---------------------------------------------------------

    @staticmethod
    def _get_domain(url: str) -> str:
        return urlparse(url).netloc

    async def _save_checkpoint(self, scheduler: Scheduler) -> None:
        """Save crawler state to checkpoint file."""
        if self._checkpoint_path is None:
            return
        state = scheduler.get_state()
        checkpoint = create_checkpoint(
            pages_crawled=self._pages_crawled,
            seen_urls=set(state["seen_urls"]),
            pending_queue=state["queue"],
            batch_number=self._batch_number,
        )
        save_checkpoint(self._checkpoint_path, checkpoint)
        _logger.debug("Checkpoint saved: %d pages", self._pages_crawled)

    async def _apply_request_hooks(
        self, request: CrawlRequest,
    ) -> CrawlRequest | None:
        current = request
        for hook in self._hooks:
            maybe = await hook.on_request(current)
            if maybe is None:
                return None
            current = maybe
        return current

    async def _apply_response_hooks(
        self, response: CrawlResponse,
    ) -> CrawlResponse | None:
        current = response
        for hook in self._hooks:
            maybe = await hook.on_response(current)
            if maybe is None:
                return None
            current = maybe
        return current

    async def _worker(
        self,
        scheduler: Scheduler,
        pipeline: Pipeline | None,
        item_queue: asyncio.Queue,
    ) -> None:
        """Worker coroutine: fetch, parse, enqueue new URLs."""
        assert self._fetcher is not None

        while not self._shutdown_event.is_set():
            request = await scheduler.get_nowait()
            if request is None:
                async with self._counter_lock:
                    # No work available; stop if page budget exhausted.
                    if self._pages_crawled >= self._max_pages:
                        break
                await asyncio.sleep(0.1)
                continue

            # Claim a page-budget slot atomically before fetching.
            # Using (_pages_crawled + _active_tasks) prevents concurrent workers
            # from all passing the check simultaneously and overshooting max_pages.
            async with self._counter_lock:
                if self._pages_crawled + self._active_tasks >= self._max_pages:
                    break
                self._active_tasks += 1

            try:
                # Apply request hooks.  When a hook returns None the request
                # is skipped; the finally block will still decrement
                # _active_tasks exactly once, so no manual decrement here.
                hooked_request = await self._apply_request_hooks(request)
                if hooked_request is None:
                    continue
                request = hooked_request

                response = await self._fetcher.fetch(request)
                async with self._counter_lock:
                    self._pages_crawled += 1
                    self._stats["pages_crawled"] += 1

                if response.error:
                    _logger.warning(
                        "Fetch error for %s: %s",
                        request.url, response.error,
                    )
                    async with self._counter_lock:
                        self._stats["errors"] += 1

                if response.from_cache:
                    async with self._counter_lock:
                        self._stats["cache_hits"] += 1

                # Apply response hooks
                hooked_response = await self._apply_response_hooks(
                    response,
                )
                if hooked_response is not None:
                    response = hooked_response

                    if response.status_code == 200 and response.content:
                        # Extract data
                        if self._schema is not None:
                            try:
                                item = extract_typed_data(response, self._schema)
                            except ExtractionError as e:
                                _logger.error("Extraction error: %s", e)
                                item = None
                        else:
                            item = extract_data(response)

                        if item is not None:
                            # Send to pipeline and stream queue
                            if pipeline is not None:
                                await pipeline.add(item)
                            await item_queue.put(item)
                            async with self._counter_lock:
                                self._stats["items_extracted"] += 1

                        # Queue discovered links
                        if request.depth < self._max_depth:
                            has_links = (
                                self._schema is None
                                and item is not None
                                and hasattr(item, "links")
                            )
                            if has_links:
                                links = item.links  # type: ignore[attr-defined]
                            else:
                                links = extract_links(response.content, response.url)

                            new_requests = []
                            for link in links:
                                domain = self._get_domain(link)
                                if (self._same_domain
                                        and domain not in self._allowed_domains):
                                    continue
                                new_requests.append(
                                    CrawlRequest(
                                        url=link,
                                        depth=request.depth + 1,
                                        priority=-request.depth - 1,
                                    )
                                )
                            await scheduler.add_many(new_requests)

                _logger.debug(
                    "[%d/%d] %d %s",
                    self._pages_crawled,
                    self._max_pages,
                    response.status_code,
                    request.url[:80],
                )
            finally:
                async with self._counter_lock:
                    self._active_tasks -= 1

    async def _crawl_iter(self) -> AsyncIterator[BaseModel]:
        """Core crawl loop. Yields extracted items as they arrive."""
        import time
        self._start_time = time.monotonic()

        # Resolve allowed domains from seed URLs
        for url in self._start_urls:
            self._allowed_domains.add(self._get_domain(url))

        scheduler = Scheduler(self._config)

        # Restore from checkpoint or start fresh
        if self._resume_from is not None:
            cp = self._resume_from
            self._pages_crawled = cp.pages_crawled
            self._batch_number = cp.batch_number
            state = {
                "seen_urls": cp.seen_urls,
                "queue": [
                    (item["priority"], item["counter"], item["request"])
                    for item in cp.pending_queue
                ],
            }
            scheduler.restore_state(state)
            _logger.info(
                "Resumed from checkpoint: %d pages, %d pending URLs",
                cp.pages_crawled,
                len(cp.pending_queue),
            )
        else:
            for url in self._start_urls:
                await scheduler.add(
                    CrawlRequest(url=url, depth=0, priority=0)
                )

        # Build pipeline only when output path is set
        pipeline: Pipeline | None = None
        if self._output is not None:
            pipeline = Pipeline(
                self._config, self._output, self._schema,
                self._output_format,
            )

        item_queue: asyncio.Queue = asyncio.Queue()

        # Ensure we have a fetcher (user may not use context manager)
        owns_fetcher_locally = False
        if self._fetcher is None:
            self._fetcher = Fetcher(self._config)
            await self._fetcher.__aenter__()
            owns_fetcher_locally = True

        workers = [
            asyncio.create_task(
                self._worker(scheduler, pipeline, item_queue)
            )
            for _ in range(self._config.max_concurrent_requests)
        ]

        last_checkpoint_count = self._pages_crawled
        try:
            while not self._shutdown_event.is_set():
                async with self._counter_lock:
                    if self._pages_crawled >= self._max_pages:
                        break
                    active = self._active_tasks
                    current_pages = self._pages_crawled

                if await scheduler.is_empty() and active == 0:
                    break

                # Periodic checkpoint save
                if (self._checkpoint_interval > 0
                        and current_pages - last_checkpoint_count
                        >= self._checkpoint_interval):
                    await self._save_checkpoint(scheduler)
                    last_checkpoint_count = current_pages

                # Drain any available items from the queue
                while not item_queue.empty():
                    yield item_queue.get_nowait()

                await asyncio.sleep(0.1)

            # Drain remaining items
            while not item_queue.empty():
                yield item_queue.get_nowait()

        finally:
            self._shutdown_event.set()
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

            # Drain items produced during shutdown
            while not item_queue.empty():
                yield item_queue.get_nowait()

            if pipeline is not None:
                await pipeline.flush()
                pipeline.consolidate()

            if owns_fetcher_locally and self._fetcher is not None:
                await self._fetcher.__aexit__(None, None, None)
                self._fetcher = None

        # Clean up checkpoint on successful completion
        completed = (
            self._pages_crawled >= self._max_pages
            or (await scheduler.is_empty() and self._active_tasks == 0)
        )
        if completed and self._checkpoint_path is not None:
            delete_checkpoint(self._checkpoint_path)
            _logger.debug("Checkpoint deleted (crawl complete)")

        _logger.info("Crawl complete: %d pages", self._pages_crawled)
        if self._output:
            _logger.info("Output saved to: %s", self._output)


async def crawl(
    urls: list[str],
    *,
    schema: type[BaseModel] | None = None,
    **kwargs,
) -> list[BaseModel]:
    """One-shot crawl. Creates a Crawler, runs it, returns results.

    Example:
        results = await crawl(urls=["https://example.com"], max_pages=5)
    """
    async with Crawler(urls, schema=schema, **kwargs) as c:
        return await c.run()
