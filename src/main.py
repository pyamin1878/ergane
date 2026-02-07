import asyncio
import signal
from contextlib import ExitStack
from pathlib import Path
from typing import Type
from urllib.parse import urlparse

import click
from pydantic import BaseModel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.config import load_config, merge_config
from src.crawler import (
    Fetcher,
    Pipeline,
    Scheduler,
    extract_data,
    extract_links,
    extract_typed_data,
)
from src.crawler.checkpoint import (
    CHECKPOINT_FILE,
    CrawlerCheckpoint,
    create_checkpoint,
    delete_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from src.logging import get_logger, setup_logging
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
        checkpoint_interval: int = 100,
        show_progress: bool = True,
    ):
        self.config = config
        self.start_urls = start_urls
        self.output_path = output_path
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.same_domain = same_domain
        self.output_schema = output_schema
        self.output_format = output_format
        self.checkpoint_interval = checkpoint_interval
        self.show_progress = show_progress
        self.allowed_domains: set[str] = set()

        self._shutdown = asyncio.Event()
        self._pages_crawled = 0
        self._active_tasks = 0
        self._counter_lock = asyncio.Lock()
        self._batch_number = 0
        self._checkpoint_path = Path(CHECKPOINT_FILE)
        self._logger = get_logger()
        self._progress: Progress | None = None
        self._progress_task = None

    def _get_domain(self, url: str) -> str:
        return urlparse(url).netloc

    async def _save_checkpoint(self, scheduler: Scheduler) -> None:
        """Save current crawler state to checkpoint file."""
        state = scheduler.get_state()
        checkpoint = create_checkpoint(
            pages_crawled=self._pages_crawled,
            seen_urls=set(state["seen_urls"]),
            pending_queue=state["queue"],
            batch_number=self._batch_number,
        )
        save_checkpoint(self._checkpoint_path, checkpoint)
        self._logger.debug(f"Checkpoint saved: {self._pages_crawled} pages")

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

                if response.error:
                    self._logger.warning(
                        f"Fetch error for {request.url}: {response.error}"
                    )

                if response.status_code == 200 and response.content:
                    # Use custom schema or legacy ParsedItem
                    if self.output_schema is not None:
                        try:
                            item = extract_typed_data(response, self.output_schema)
                            await pipeline.add(item)
                        except ExtractionError as e:
                            self._logger.error(f"Extraction error: {e}")
                    else:
                        item = extract_data(response)
                        await pipeline.add(item)

                    # Queue discovered links
                    if request.depth < self.max_depth:
                        if self.output_schema is None:
                            links = item.links
                        else:
                            # Lightweight link-only parse (no title/text/selectors)
                            links = extract_links(response.content, response.url)

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

                # Update progress or log
                truncated_url = request.url[:50] + "..." if len(request.url) > 50 else request.url
                if self._progress and self._progress_task is not None:
                    self._progress.update(
                        self._progress_task,
                        advance=1,
                        url=truncated_url,
                    )
                else:
                    self._logger.info(
                        f"[{current_count}/{self.max_pages}] "
                        f"{response.status_code} {request.url[:80]}"
                    )

            finally:
                async with self._counter_lock:
                    self._active_tasks -= 1

    async def run(self, resume_checkpoint: CrawlerCheckpoint | None = None) -> None:
        """Run the crawler."""
        for url in self.start_urls:
            self.allowed_domains.add(self._get_domain(url))

        scheduler = Scheduler(self.config)
        pipeline = Pipeline(
            self.config, self.output_path, self.output_schema, self.output_format
        )

        # Restore from checkpoint or start fresh
        if resume_checkpoint:
            self._pages_crawled = resume_checkpoint.pages_crawled
            self._batch_number = resume_checkpoint.batch_number
            # Restore scheduler state
            state = {
                "seen_urls": resume_checkpoint.seen_urls,
                "queue": [
                    (item["priority"], item["counter"], item["request"])
                    for item in resume_checkpoint.pending_queue
                ],
            }
            scheduler.restore_state(state)
            self._logger.info(
                f"Resumed from checkpoint: {self._pages_crawled} pages, "
                f"{len(resume_checkpoint.pending_queue)} pending URLs"
            )
        else:
            for url in self.start_urls:
                await scheduler.add(CrawlRequest(url=url, depth=0, priority=0))

        # Setup progress bar context
        progress_context = (
            Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("[cyan]{task.fields[url]}"),
            )
            if self.show_progress
            else None
        )

        async with Fetcher(self.config) as fetcher:
            workers = [
                asyncio.create_task(self._worker(fetcher, scheduler, pipeline))
                for _ in range(self.config.max_concurrent_requests)
            ]

            with ExitStack() as stack:
                try:
                    # Enter progress context if enabled
                    if progress_context:
                        self._progress = stack.enter_context(progress_context)
                        self._progress_task = self._progress.add_task(
                            "Crawling",
                            total=self.max_pages,
                            url="",
                            completed=self._pages_crawled,
                        )

                    last_checkpoint_count = self._pages_crawled

                    while not self._shutdown.is_set():
                        async with self._counter_lock:
                            if self._pages_crawled >= self.max_pages:
                                break
                            active = self._active_tasks
                            current_pages = self._pages_crawled

                        if await scheduler.is_empty() and active == 0:
                            break

                        # Save checkpoint periodically
                        if current_pages - last_checkpoint_count >= self.checkpoint_interval:
                            await self._save_checkpoint(scheduler)
                            last_checkpoint_count = current_pages

                        await asyncio.sleep(0.5)

                finally:
                    self._shutdown.set()
                    for worker in workers:
                        worker.cancel()

                    await asyncio.gather(*workers, return_exceptions=True)
                    await pipeline.flush()
                    pipeline.consolidate()
                    self._progress = None

        # Clean up checkpoint on successful completion
        if self._pages_crawled >= self.max_pages or (
            await scheduler.is_empty() and self._active_tasks == 0
        ):
            delete_checkpoint(self._checkpoint_path)
            self._logger.debug("Checkpoint deleted (crawl complete)")

        self._logger.info(f"Crawl complete: {self._pages_crawled} pages")
        self._logger.info(f"Output saved to: {self.output_path}")


@click.command()
@click.option(
    "--url", "-u", multiple=True,
    help="Start URL(s) to crawl. Repeat for multiple.",
)
@click.option(
    "--output", "-o", default="output.parquet",
    help="Output file path (.parquet, .csv, .xlsx).",
)
@click.option(
    "--max-pages", "-n", default=None, type=int,
    help="Maximum pages to crawl (default: 100).",
)
@click.option(
    "--max-depth", "-d", default=None, type=int,
    help="Maximum link-follow depth (default: 3). 0 = seed only.",
)
@click.option(
    "--concurrency", "-c", default=None, type=int,
    help="Concurrent requests (default: 10).",
)
@click.option(
    "--rate-limit", "-r", default=None, type=float,
    help="Max requests/sec per domain (default: 10).",
)
@click.option(
    "--timeout", "-t", default=None, type=float,
    help="Request timeout in seconds (default: 30).",
)
@click.option(
    "--same-domain/--any-domain", default=None,
    help="Restrict to same domain (default) or allow cross-domain.",
)
@click.option(
    "--ignore-robots", is_flag=True, default=None,
    help="Ignore robots.txt restrictions.",
)
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
    default=None,
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
@click.option(
    "--proxy",
    "-x",
    help="HTTP/HTTPS proxy URL (e.g., http://localhost:8080)",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from last checkpoint",
)
@click.option(
    "--checkpoint-interval",
    default=None,
    type=int,
    help="Save checkpoint every N pages (default: 100)",
)
@click.option(
    "--log-level",
    default=None,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level (default: INFO)",
)
@click.option(
    "--log-file",
    help="Write logs to file",
)
@click.option(
    "--no-progress",
    is_flag=True,
    help="Disable progress bar",
)
@click.option(
    "--config",
    "-C",
    "config_file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file path",
)
@click.option(
    "--cache",
    is_flag=True,
    help="Enable response caching",
)
@click.option(
    "--cache-dir",
    type=click.Path(path_type=Path),
    default=Path(".ergane_cache"),
    help="Cache directory",
)
@click.option(
    "--cache-ttl",
    type=int,
    default=3600,
    help="Cache TTL in seconds",
)
def main(
    url: tuple[str, ...],
    output: str,
    max_pages: int | None,
    max_depth: int | None,
    concurrency: int | None,
    rate_limit: float | None,
    timeout: float | None,
    same_domain: bool | None,
    ignore_robots: bool | None,
    schema: Path | None,
    output_format: str | None,
    preset: str | None,
    list_presets: bool,
    proxy: str | None,
    resume: bool,
    checkpoint_interval: int | None,
    log_level: str | None,
    log_file: str | None,
    no_progress: bool,
    config_file: Path | None,
    cache: bool,
    cache_dir: Path,
    cache_ttl: int,
) -> None:
    """Ergane - High-performance async web scraper.

    \b
    Presets (no schema needed):
      ergane --preset quotes -o quotes.csv
      ergane --preset hacker-news -o stories.xlsx -n 200
      ergane --list-presets            # show all presets

    \b
    Custom URLs:
      ergane -u https://example.com -o data.parquet
      ergane -u https://a.com -u https://b.com -n 50

    \b
    Custom schema:
      ergane -u https://shop.com -s schema.yaml -o items.csv

    \b
    Caching (instant reruns during development):
      ergane --preset quotes --cache -n 10 -o quotes.csv

    \b
    Resume an interrupted crawl:
      ergane -u https://example.com -n 1000 --resume
    """
    # Handle --list-presets
    if list_presets:
        print_presets_table()
        return

    # Load config file
    file_config = load_config(config_file)

    # Build CLI args dict
    cli_args = {
        "rate_limit": rate_limit,
        "concurrency": concurrency,
        "timeout": timeout,
        "respect_robots_txt": not ignore_robots if ignore_robots is not None else None,
        "user_agent": None,
        "proxy": proxy,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "same_domain": same_domain,
        "output_format": output_format,
        "level": log_level,
        "file": log_file,
        "checkpoint_interval": checkpoint_interval,
    }

    # Merge config file with CLI args
    merged = merge_config(file_config, cli_args)

    # Setup logging
    effective_log_level = merged.get("level", "INFO") or "INFO"
    effective_log_file = merged.get("file")
    logger = setup_logging(effective_log_level, effective_log_file)

    # Handle preset configuration
    start_urls: list[str] = []
    output_schema = None

    # Get effective values with defaults
    effective_max_pages = merged.get("max_pages", 100) or 100
    effective_max_depth = merged.get("max_depth", 3) or 3
    effective_concurrency = merged.get("concurrency", 10) or 10
    effective_rate_limit = merged.get("rate_limit", 10.0) or 10.0
    effective_timeout = merged.get("timeout", 30.0) or 30.0
    effective_proxy = merged.get("proxy")
    effective_same_domain = merged.get("same_domain", True)
    if effective_same_domain is None:
        effective_same_domain = True
    effective_respect_robots = merged.get("respect_robots_txt", True)
    if effective_respect_robots is None:
        effective_respect_robots = True
    effective_output_format = merged.get("output_format", "auto") or "auto"
    effective_checkpoint_interval = merged.get("checkpoint_interval", 100) or 100

    if preset:
        try:
            preset_config = get_preset(preset)
            logger.info(f"Using preset: {preset_config.name}")

            # Load preset schema
            schema_path = get_preset_schema_path(preset)
            output_schema = load_schema_from_yaml(schema_path)
            logger.info(f"Loaded schema: {output_schema.__name__}")

            # Use preset start URLs if none provided
            if not url:
                start_urls = preset_config.start_urls
            else:
                start_urls = list(url)

            # Apply preset defaults if not overridden via CLI
            if max_pages is None and "max_pages" not in file_config.get("defaults", {}):
                effective_max_pages = preset_config.defaults.get("max_pages", 100)
            if max_depth is None and "max_depth" not in file_config.get("defaults", {}):
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
                logger.info(f"Loaded schema: {output_schema.__name__}")
            except Exception as e:
                raise click.ClickException(f"Failed to load schema: {e}")

        start_urls = list(url)

    # Validate that we have URLs
    if not start_urls:
        raise click.ClickException(
            "At least one URL is required. Use --url/-u option or --preset."
        )

    # Check for resume checkpoint
    checkpoint_path = Path(CHECKPOINT_FILE)
    resume_checkpoint: CrawlerCheckpoint | None = None
    if resume:
        resume_checkpoint = load_checkpoint(checkpoint_path)
        if resume_checkpoint is None:
            logger.warning("No checkpoint found, starting fresh")
        else:
            logger.info(f"Found checkpoint from {resume_checkpoint.timestamp}")

    config = CrawlConfig(
        max_requests_per_second=effective_rate_limit,
        max_concurrent_requests=effective_concurrency,
        request_timeout=effective_timeout,
        respect_robots_txt=effective_respect_robots,
        output_schema=output_schema,
        proxy=effective_proxy,
        cache_enabled=cache,
        cache_dir=cache_dir,
        cache_ttl=cache_ttl,
    )

    crawler = Crawler(
        config=config,
        start_urls=start_urls,
        output_path=output,
        max_pages=effective_max_pages,
        max_depth=effective_max_depth,
        same_domain=effective_same_domain,
        output_schema=output_schema,
        output_format=effective_output_format,
        checkpoint_interval=effective_checkpoint_interval,
        show_progress=not no_progress,
    )

    def handle_shutdown(signum, frame):
        logger.info("Shutting down gracefully...")
        crawler._shutdown.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    asyncio.run(crawler.run(resume_checkpoint=resume_checkpoint))


if __name__ == "__main__":
    main()
