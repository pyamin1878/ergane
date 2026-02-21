"""Configuration file loading for Ergane."""

import logging
from pathlib import Path

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
