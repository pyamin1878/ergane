"""Configuration file loading for Ergane."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_LOCATIONS = [
    Path.home() / ".ergane.yaml",
    Path.cwd() / ".ergane.yaml",
    Path.cwd() / "ergane.yaml",
]

# Top-level sections recognised in the config file.
_VALID_SECTIONS = {"crawler", "defaults", "logging"}

# Known keys within each section.
_VALID_SECTION_KEYS: dict[str, set[str]] = {
    "crawler": {
        "max_pages", "max_depth", "concurrency", "rate_limit", "timeout",
        "same_domain", "respect_robots_txt", "proxy", "user_agent",
        "cache", "cache_dir", "cache_ttl",
    },
    "defaults": {
        "max_pages", "max_depth", "concurrency", "rate_limit", "timeout",
        "same_domain", "respect_robots_txt", "proxy",
        "checkpoint_interval", "output_format",
    },
    "logging": {"level", "file"},
}

_config_logger = logging.getLogger("ergane.config")


def _warn_unknown_keys(config: dict, source: str) -> None:
    """Emit warnings for unrecognised top-level sections and keys."""
    for section, keys in config.items():
        if section not in _VALID_SECTIONS:
            _config_logger.warning(
                "Config file '%s': unknown section '%s' (ignored)", source, section
            )
            continue
        if not isinstance(keys, dict):
            continue
        valid_keys = _VALID_SECTION_KEYS.get(section, set())
        for key in keys:
            if key not in valid_keys:
                _config_logger.warning(
                    "Config file '%s': unknown key '%s.%s' (ignored)",
                    source, section, key,
                )


def load_config(path: Path | None = None) -> dict:
    """Load config from file, checking default locations.

    Args:
        path: Explicit config file path. If None, searches default locations.

    Returns:
        Configuration dictionary, or empty dict if no config found.
    """
    if path:
        locations = [path]
    else:
        locations = CONFIG_LOCATIONS

    for loc in locations:
        if loc.exists():
            with open(loc) as f:
                data = yaml.safe_load(f) or {}
            _warn_unknown_keys(data, str(loc))
            return data
    return {}


def merge_config(file_config: dict, cli_args: dict) -> dict:
    """Merge config file with CLI args (CLI takes precedence).

    Args:
        file_config: Configuration from YAML file.
        cli_args: Arguments from CLI.

    Returns:
        Merged configuration dictionary.
    """
    result = {}
    # Flatten nested config sections
    for section in ["crawler", "defaults", "logging"]:
        result.update(file_config.get(section, {}))
    # CLI overrides (only non-None values)
    for key, value in cli_args.items():
        if value is not None:
            result[key] = value
    return result


@dataclass
class CrawlOptions:
    """Unified crawl options built once from file config + CLI args.

    Replaces the ad-hoc merge_config() + _coalesce() pattern in main.py.
    All defaults live here; callers override only the fields they care about.
    """

    # Crawl limits
    max_pages: int = 100
    max_depth: int = 3
    concurrency: int = 10
    rate_limit: float = 10.0
    timeout: float = 30.0

    # Domain / robots
    same_domain: bool = True
    respect_robots_txt: bool = True
    proxy: str | None = None

    # Output
    output: str = "output.parquet"
    output_format: str = "auto"

    # Caching
    cache: bool = False
    cache_dir: Path = field(default_factory=lambda: Path(".ergane_cache"))
    cache_ttl: int = 3600

    # Checkpointing
    checkpoint_interval: int = 100
    checkpoint_path: Path | None = None

    # Logging (resolved separately in main, kept here for completeness)
    log_level: str = "INFO"
    log_file: str | None = None

    @classmethod
    def from_sources(
        cls,
        file_config: dict[str, Any],
        *,
        max_pages: int | None = None,
        max_depth: int | None = None,
        concurrency: int | None = None,
        rate_limit: float | None = None,
        timeout: float | None = None,
        same_domain: bool | None = None,
        respect_robots_txt: bool | None = None,
        proxy: str | None = None,
        output: str = "output.parquet",
        output_format: str | None = None,
        cache: bool = False,
        cache_dir: Path = Path(".ergane_cache"),
        cache_ttl: int = 3600,
        checkpoint_interval: int | None = None,
        checkpoint_path: Path | None = None,
        log_level: str | None = None,
        log_file: str | None = None,
    ) -> "CrawlOptions":
        """Build CrawlOptions by merging file config with explicit CLI values.

        File config is applied first; non-None CLI values take precedence.
        Defaults come from the dataclass field defaults above.
        """
        opts = cls()

        # Apply file config sections (flattened, same order as merge_config)
        flat: dict[str, Any] = {}
        for section in ("crawler", "defaults", "logging"):
            flat.update(file_config.get(section, {}))

        def _fc(key: str) -> Any:
            """Return value from flat file config, or sentinel None if absent."""
            return flat.get(key)

        # File config layer (only overrides the dataclass default when present)
        if _fc("max_pages") is not None:
            opts.max_pages = int(_fc("max_pages"))
        if _fc("max_depth") is not None:
            opts.max_depth = int(_fc("max_depth"))
        if _fc("concurrency") is not None:
            opts.concurrency = int(_fc("concurrency"))
        if _fc("rate_limit") is not None:
            opts.rate_limit = float(_fc("rate_limit"))
        if _fc("timeout") is not None:
            opts.timeout = float(_fc("timeout"))
        if _fc("same_domain") is not None:
            opts.same_domain = bool(_fc("same_domain"))
        if _fc("respect_robots_txt") is not None:
            opts.respect_robots_txt = bool(_fc("respect_robots_txt"))
        if _fc("proxy") is not None:
            opts.proxy = str(_fc("proxy"))
        if _fc("output_format") is not None:
            opts.output_format = str(_fc("output_format"))
        if _fc("cache") is not None:
            opts.cache = bool(_fc("cache"))
        if _fc("cache_dir") is not None:
            opts.cache_dir = Path(_fc("cache_dir"))
        if _fc("cache_ttl") is not None:
            opts.cache_ttl = int(_fc("cache_ttl"))
        if _fc("checkpoint_interval") is not None:
            opts.checkpoint_interval = int(_fc("checkpoint_interval"))
        if _fc("level") is not None:
            opts.log_level = str(_fc("level"))
        if _fc("file") is not None:
            opts.log_file = str(_fc("file"))

        # CLI layer — non-None values override everything
        if max_pages is not None:
            opts.max_pages = max_pages
        if max_depth is not None:
            opts.max_depth = max_depth
        if concurrency is not None:
            opts.concurrency = concurrency
        if rate_limit is not None:
            opts.rate_limit = rate_limit
        if timeout is not None:
            opts.timeout = timeout
        if same_domain is not None:
            opts.same_domain = same_domain
        if respect_robots_txt is not None:
            opts.respect_robots_txt = respect_robots_txt
        if proxy is not None:
            opts.proxy = proxy
        if output_format is not None:
            opts.output_format = output_format
        if cache:
            opts.cache = True
        opts.cache_dir = cache_dir
        opts.cache_ttl = cache_ttl
        if checkpoint_interval is not None:
            opts.checkpoint_interval = checkpoint_interval
        if checkpoint_path is not None:
            opts.checkpoint_path = checkpoint_path
        if log_level is not None:
            opts.log_level = log_level
        if log_file is not None:
            opts.log_file = log_file

        opts.output = output

        return opts
