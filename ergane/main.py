"""Ergane CLI — thin wrapper around the crawl engine.

The Crawler class lives in src.crawler.engine; this module adds:
- Click CLI with 20+ options
- Rich progress bar
- Signal handling for graceful shutdown
- Preset/config-file resolution
"""

import asyncio
import datetime
import signal
from pathlib import Path

import click
from rich.console import Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from ergane.config import load_config, merge_config
from ergane.crawler.checkpoint import (
    CHECKPOINT_FILE,
    CrawlerCheckpoint,
    load_checkpoint,
)
from ergane.crawler.engine import Crawler
from ergane.logging import setup_logging
from ergane.presets import get_preset, get_preset_schema_path, list_presets
from ergane.schema import load_schema_from_yaml


def _make_renderable(crawler, progress, task_id: int) -> Group:
    """Build the Rich Live renderable from current crawler stats."""
    stats = crawler.stats
    progress.update(task_id, completed=stats["pages_crawled"])

    elapsed = stats["elapsed"]
    elapsed_str = str(datetime.timedelta(seconds=int(elapsed)))
    speed_str = f"{stats['pages_per_sec']:.1f} p/s"

    table = Table(box=None, padding=(0, 2), show_header=True, header_style="bold")
    table.add_column("Extracted", style="green", justify="right")
    table.add_column("Errors", style="red", justify="right")
    table.add_column("Cache hits", style="cyan", justify="right")
    table.add_column("Elapsed", justify="right")
    table.add_column("Speed", justify="right")
    table.add_row(
        str(stats["items_extracted"]),
        str(stats["errors"]),
        str(stats["cache_hits"]),
        elapsed_str,
        speed_str,
    )

    return Group(progress, table)


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


_GROUP_ONLY_FLAGS = {"--version", "--help", "-h"}


class DefaultGroup(click.Group):
    """A Click group that defaults to 'crawl' when no subcommand is given."""

    def parse_args(self, ctx, args):
        # If the first arg is an option that belongs to the group itself
        # (--version, --help) do NOT prepend 'crawl'; let the group handle it.
        if args and args[0].startswith("-") and args[0] not in _GROUP_ONLY_FLAGS:
            args = ["crawl"] + args
        # If no args at all, show help (already handled by invoke_without_command)
        return super().parse_args(ctx, args)


@click.group(cls=DefaultGroup, invoke_without_command=True)
@click.version_option(version="0.7.0", prog_name="ergane")
@click.pass_context
def cli(ctx):
    """Ergane - High-performance async web scraper."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option(
    "--url", "-u", multiple=True,
    help="Start URL(s) to crawl. Repeat for multiple.",
)
@click.option(
    "--output", "-o", default="output.parquet",
    help="Output file path (.parquet, .csv, .xlsx, .json, .jsonl, .sqlite).",
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
    type=click.Choice(["auto", "csv", "excel", "parquet", "json", "jsonl", "sqlite"]),
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
def crawl(
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
    """Crawl websites and extract data.

    \b
    Presets (no schema needed):
      ergane crawl --preset quotes -o quotes.csv
      ergane crawl --preset hacker-news -o stories.xlsx -n 200
      ergane crawl --list-presets            # show all presets

    \b
    Custom URLs:
      ergane crawl -u https://example.com -o data.parquet
      ergane crawl -u https://a.com -u https://b.com -n 50

    \b
    Custom schema:
      ergane crawl -u https://shop.com -s schema.yaml -o items.csv

    \b
    Caching (instant reruns during development):
      ergane crawl --preset quotes --cache -n 10 -o quotes.csv

    \b
    Resume an interrupted crawl:
      ergane crawl -u https://example.com -n 1000 --resume
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

    # Get effective values with defaults.
    # Use explicit None checks (not `or default`) so that users who explicitly
    # pass 0 or 0.0 reach the validation step rather than being silently
    # replaced with the default value (because 0 is falsy in Python).
    def _coalesce(val, default):
        return val if val is not None else default

    effective_max_pages = _coalesce(merged.get("max_pages"), 100)
    effective_max_depth = _coalesce(merged.get("max_depth"), 3)
    effective_concurrency = _coalesce(merged.get("concurrency"), 10)
    effective_rate_limit = _coalesce(merged.get("rate_limit"), 10.0)
    effective_timeout = _coalesce(merged.get("timeout"), 30.0)
    effective_proxy = merged.get("proxy")
    effective_same_domain = _coalesce(merged.get("same_domain"), True)
    effective_respect_robots = _coalesce(merged.get("respect_robots_txt"), True)
    effective_output_format = _coalesce(merged.get("output_format"), "auto")

    # Validate effective parameter values before doing any real work.
    if effective_max_pages <= 0:
        raise click.ClickException("--max-pages must be a positive integer")
    if effective_max_depth < 0:
        raise click.ClickException("--max-depth must be 0 or greater")
    if effective_concurrency <= 0:
        raise click.ClickException("--concurrency must be a positive integer")
    if effective_rate_limit <= 0:
        raise click.ClickException("--rate-limit must be a positive number")
    if effective_timeout <= 0:
        raise click.ClickException("--timeout must be a positive number")

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
            raise click.ClickException(str(e)) from e
        except FileNotFoundError as e:
            raise click.ClickException(f"Preset schema not found: {e}") from e
        except Exception as e:
            raise click.ClickException(f"Failed to load preset: {e}") from e
    else:
        # Load schema if provided directly
        if schema:
            try:
                output_schema = load_schema_from_yaml(schema)
                logger.info(f"Loaded schema: {output_schema.__name__}")
            except Exception as e:
                raise click.ClickException(f"Failed to load schema: {e}") from e

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

    effective_checkpoint_interval = merged.get("checkpoint_interval", 100) or 100

    # Build the Crawler using the new engine API
    crawler = Crawler(
        urls=start_urls,
        schema=output_schema,
        concurrency=effective_concurrency,
        max_pages=effective_max_pages,
        max_depth=effective_max_depth,
        rate_limit=effective_rate_limit,
        timeout=effective_timeout,
        same_domain=effective_same_domain,
        respect_robots_txt=effective_respect_robots,
        proxy=effective_proxy,
        output=output,
        output_format=effective_output_format,  # type: ignore[arg-type]
        cache=cache,
        cache_dir=cache_dir,
        cache_ttl=cache_ttl,
        checkpoint_interval=effective_checkpoint_interval,
        checkpoint_path=checkpoint_path,
        resume_from=resume_checkpoint,
    )

    def handle_shutdown(signum, frame):
        logger.info("Shutting down gracefully...")
        crawler.shutdown()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    async def _run_with_progress():
        async with crawler:
            if no_progress:
                await crawler.run()
            else:
                progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TimeRemainingColumn(),
                )
                task_id = progress.add_task("Crawling", total=effective_max_pages)

                with Live(
                    _make_renderable(crawler, progress, task_id),
                    refresh_per_second=4,
                    transient=False,
                ) as live:
                    async for _item in crawler.stream():
                        live.update(_make_renderable(crawler, progress, task_id))

    asyncio.run(_run_with_progress())


@cli.command()
def mcp():
    """Start the Ergane MCP server (stdio transport)."""
    from ergane.mcp import run

    run()


if __name__ == "__main__":
    cli()
