import asyncio
import signal
from urllib.parse import urlparse

import click

from src.crawler import Fetcher, Pipeline, Scheduler, extract_data
from src.models import CrawlConfig, CrawlRequest


class Crawler:
    """Orchestrates the crawl: scheduler -> fetcher -> parser -> pipeline."""

    def __init__(
        self,
        config: CrawlConfig,
        start_urls: list[str],
        output_path: str,
        max_pages: int,
        max_depth: int,
        same_domain: bool,
    ):
        self.config = config
        self.start_urls = start_urls
        self.output_path = output_path
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.same_domain = same_domain
        self.allowed_domains: set[str] = set()

        self._shutdown = asyncio.Event()
        self._pages_crawled = 0
        self._active_tasks = 0
        self._counter_lock = asyncio.Lock()

    def _get_domain(self, url: str) -> str:
        return urlparse(url).netloc

    async def _worker(
        self,
        fetcher: Fetcher,
        scheduler: Scheduler,
        pipeline: Pipeline,
    ) -> None:
        """Worker that fetches, parses, and queues new URLs."""
        while not self._shutdown.is_set():
            async with self._counter_lock:
                if self._pages_crawled >= self.max_pages:
                    break

            request = await scheduler.get_nowait()
            if request is None:
                await asyncio.sleep(0.1)
                continue

            async with self._counter_lock:
                self._active_tasks += 1
            try:
                response = await fetcher.fetch(request)
                async with self._counter_lock:
                    self._pages_crawled += 1
                    current_count = self._pages_crawled

                if response.status_code == 200 and response.content:
                    item = extract_data(response)
                    await pipeline.add(item)

                    if request.depth < self.max_depth:
                        new_requests = []
                        for link in item.links:
                            domain = self._get_domain(link)
                            if self.same_domain and domain not in self.allowed_domains:
                                continue

                            new_requests.append(
                                CrawlRequest(
                                    url=link,
                                    depth=request.depth + 1,
                                    priority=-request.depth - 1,
                                )
                            )
                        await scheduler.add_many(new_requests)

                click.echo(
                    f"[{current_count}/{self.max_pages}] "
                    f"{response.status_code} {request.url[:80]}"
                )

            finally:
                async with self._counter_lock:
                    self._active_tasks -= 1

    async def run(self) -> None:
        """Run the crawler."""
        for url in self.start_urls:
            self.allowed_domains.add(self._get_domain(url))

        scheduler = Scheduler(self.config)
        pipeline = Pipeline(self.config, self.output_path)

        for url in self.start_urls:
            await scheduler.add(CrawlRequest(url=url, depth=0, priority=0))

        async with Fetcher(self.config) as fetcher:
            workers = [
                asyncio.create_task(self._worker(fetcher, scheduler, pipeline))
                for _ in range(self.config.max_concurrent_requests)
            ]

            try:
                while not self._shutdown.is_set():
                    async with self._counter_lock:
                        if self._pages_crawled >= self.max_pages:
                            break
                        active = self._active_tasks

                    if await scheduler.is_empty() and active == 0:
                        break

                    await asyncio.sleep(0.5)

            finally:
                self._shutdown.set()
                for worker in workers:
                    worker.cancel()

                await asyncio.gather(*workers, return_exceptions=True)
                await pipeline.flush()
                pipeline.consolidate()

        click.echo(f"\nCrawl complete: {self._pages_crawled} pages")
        click.echo(f"Output saved to: {self.output_path}")


@click.command()
@click.option("--url", "-u", multiple=True, required=True, help="Start URL(s)")
@click.option("--output", "-o", default="output.parquet", help="Output file path")
@click.option("--max-pages", "-n", default=100, help="Maximum pages to crawl")
@click.option("--max-depth", "-d", default=3, help="Maximum crawl depth")
@click.option("--concurrency", "-c", default=10, help="Concurrent requests")
@click.option("--rate-limit", "-r", default=10.0, help="Requests per second per domain")
@click.option("--timeout", "-t", default=30.0, help="Request timeout in seconds")
@click.option("--same-domain/--any-domain", default=True, help="Stay on same domain")
@click.option("--ignore-robots", is_flag=True, help="Ignore robots.txt")
def main(
    url: tuple[str, ...],
    output: str,
    max_pages: int,
    max_depth: int,
    concurrency: int,
    rate_limit: float,
    timeout: float,
    same_domain: bool,
    ignore_robots: bool,
) -> None:
    """Ergane - High-performance async web scraper."""
    config = CrawlConfig(
        max_requests_per_second=rate_limit,
        max_concurrent_requests=concurrency,
        request_timeout=timeout,
        respect_robots_txt=not ignore_robots,
    )

    crawler = Crawler(
        config=config,
        start_urls=list(url),
        output_path=output,
        max_pages=max_pages,
        max_depth=max_depth,
        same_domain=same_domain,
    )

    def handle_shutdown(signum, frame):
        click.echo("\nShutting down gracefully...")
        crawler._shutdown.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
