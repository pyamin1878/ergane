import asyncio
import signal
from pathlib import Path
from typing import Type
from urllib.parse import urlparse

import click
from pydantic import BaseModel

from src.crawler import Fetcher, Pipeline, Scheduler, extract_data, extract_typed_data
from src.models import CrawlConfig, CrawlRequest
from src.presets import get_preset, get_preset_schema_path, list_presets
from src.schema import ExtractionError, load_schema_from_yaml


def print_presets_table() -> None:
    """Print a formatted table of available presets."""
    presets = list_presets()
    click.echo("\nAvailable presets:\n")
    click.echo(f"{'ID':<15} {'Name':<25} {'Description'}")
    click.echo("-" * 70)
    for preset in presets:
        click.echo(f"{preset['id']:<15} {preset['name']:<25} {preset['description']}")
    click.echo("\nUsage: ergane --preset <id> -o output.csv")
    click.echo("Example: ergane --preset quotes -o quotes.csv\n")


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
        output_schema: Type[BaseModel] | None = None,
        output_format: str = "auto",
    ):
        self.config = config
        self.start_urls = start_urls
        self.output_path = output_path
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.same_domain = same_domain
        self.output_schema = output_schema
        self.output_format = output_format
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
                    # Use custom schema or legacy ParsedItem
                    if self.output_schema is not None:
                        try:
                            item = extract_typed_data(response, self.output_schema)
                            await pipeline.add(item)
                        except ExtractionError as e:
                            click.echo(f"Extraction error: {e}", err=True)
                            # Fall back to legacy extraction for links
                            legacy_item = extract_data(response)
                            links = legacy_item.links
                    else:
                        item = extract_data(response)
                        await pipeline.add(item)
                        links = item.links

                    # Queue new URLs (only from legacy extraction or if schema didn't fail)
                    if request.depth < self.max_depth:
                        # Get links for scheduling
                        if self.output_schema is None:
                            pass  # links already set
                        else:
                            # Extract links separately for custom schemas
                            legacy_item = extract_data(response)
                            links = legacy_item.links

                        new_requests = []
                        for link in links:
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
        pipeline = Pipeline(
            self.config, self.output_path, self.output_schema, self.output_format
        )

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
@click.option("--url", "-u", multiple=True, help="Start URL(s)")
@click.option("--output", "-o", default="output.parquet", help="Output file path")
@click.option("--max-pages", "-n", default=None, type=int, help="Maximum pages to crawl")
@click.option("--max-depth", "-d", default=None, type=int, help="Maximum crawl depth")
@click.option("--concurrency", "-c", default=10, help="Concurrent requests")
@click.option("--rate-limit", "-r", default=10.0, help="Requests per second per domain")
@click.option("--timeout", "-t", default=30.0, help="Request timeout in seconds")
@click.option("--same-domain/--any-domain", default=True, help="Stay on same domain")
@click.option("--ignore-robots", is_flag=True, help="Ignore robots.txt")
@click.option(
    "--schema",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="YAML schema file for custom output fields",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["auto", "csv", "excel", "parquet"]),
    default="auto",
    help="Output format (auto-detects from file extension)",
)
@click.option(
    "--preset",
    "-p",
    help="Use a built-in preset (run --list-presets to see options)",
)
@click.option(
    "--list-presets",
    is_flag=True,
    help="Show available presets and exit",
)
def main(
    url: tuple[str, ...],
    output: str,
    max_pages: int | None,
    max_depth: int | None,
    concurrency: int,
    rate_limit: float,
    timeout: float,
    same_domain: bool,
    ignore_robots: bool,
    schema: Path | None,
    output_format: str,
    preset: str | None,
    list_presets: bool,
) -> None:
    """Ergane - High-performance async web scraper.

    Use presets for common sites:
        ergane --preset quotes -o quotes.csv
        ergane --preset hacker-news -o stories.xlsx

    Or specify URLs directly:
        ergane -u https://example.com -o data.parquet
    """
    # Handle --list-presets
    if list_presets:
        print_presets_table()
        return

    # Handle preset configuration
    start_urls: list[str] = []
    output_schema = None
    effective_max_pages = max_pages if max_pages is not None else 100
    effective_max_depth = max_depth if max_depth is not None else 3

    if preset:
        try:
            preset_config = get_preset(preset)
            click.echo(f"Using preset: {preset_config.name}")

            # Load preset schema
            schema_path = get_preset_schema_path(preset)
            output_schema = load_schema_from_yaml(schema_path)
            click.echo(f"Loaded schema: {output_schema.__name__}")

            # Use preset start URLs if none provided
            if not url:
                start_urls = preset_config.start_urls
            else:
                start_urls = list(url)

            # Apply preset defaults if not overridden
            if max_pages is None:
                effective_max_pages = preset_config.defaults.get("max_pages", 100)
            if max_depth is None:
                effective_max_depth = preset_config.defaults.get("max_depth", 3)

        except KeyError as e:
            raise click.ClickException(str(e))
        except FileNotFoundError as e:
            raise click.ClickException(f"Preset schema not found: {e}")
        except Exception as e:
            raise click.ClickException(f"Failed to load preset: {e}")
    else:
        # Load schema if provided directly
        if schema:
            try:
                output_schema = load_schema_from_yaml(schema)
                click.echo(f"Loaded schema: {output_schema.__name__}")
            except Exception as e:
                raise click.ClickException(f"Failed to load schema: {e}")

        start_urls = list(url)

    # Validate that we have URLs
    if not start_urls:
        raise click.ClickException(
            "At least one URL is required. Use --url/-u option or --preset."
        )

    config = CrawlConfig(
        max_requests_per_second=rate_limit,
        max_concurrent_requests=concurrency,
        request_timeout=timeout,
        respect_robots_txt=not ignore_robots,
        output_schema=output_schema,
    )

    crawler = Crawler(
        config=config,
        start_urls=start_urls,
        output_path=output,
        max_pages=effective_max_pages,
        max_depth=effective_max_depth,
        same_domain=same_domain,
        output_schema=output_schema,
        output_format=output_format,
    )

    def handle_shutdown(signum, frame):
        click.echo("\nShutting down gracefully...")
        crawler._shutdown.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
