"""Configuration file loading for Ergane."""

from pathlib import Path

import yaml

CONFIG_LOCATIONS = [
    Path.home() / ".ergane.yaml",
    Path.cwd() / ".ergane.yaml",
    Path.cwd() / "ergane.yaml",
]


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
                return yaml.safe_load(f) or {}
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
