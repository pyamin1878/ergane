"""Preset registry for common website scraping configurations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PresetConfig:
    """Configuration for a scraping preset."""

    name: str
    description: str
    start_urls: list[str]
    schema_file: str
    defaults: dict[str, Any]


# Registry of all available presets
PRESETS: dict[str, PresetConfig] = {
    "hacker-news": PresetConfig(
        name="Hacker News",
        description="Front page stories from news.ycombinator.com",
        start_urls=["https://news.ycombinator.com"],
        schema_file="hacker_news.yaml",
        defaults={"max_pages": 30, "max_depth": 1},
    ),
    "github-repos": PresetConfig(
        name="GitHub Repositories",
        description="Repository search results from github.com",
        start_urls=["https://github.com/search?q=python&type=repositories"],
        schema_file="github_repos.yaml",
        defaults={"max_pages": 50, "max_depth": 1},
    ),
    "reddit": PresetConfig(
        name="Reddit",
        description="Posts from reddit.com front page or subreddits",
        start_urls=["https://old.reddit.com"],
        schema_file="reddit.yaml",
        defaults={"max_pages": 50, "max_depth": 1},
    ),
    "quotes": PresetConfig(
        name="Quotes to Scrape",
        description="Quotes from quotes.toscrape.com (demo/testing site)",
        start_urls=["https://quotes.toscrape.com"],
        schema_file="quotes_toscrape.yaml",
        defaults={"max_pages": 10, "max_depth": 2},
    ),
}


def get_schemas_dir() -> Path:
    """Get the path to the schemas directory."""
    return Path(__file__).parent / "schemas"


def list_presets() -> list[dict[str, str]]:
    """List all available presets with their descriptions.

    Returns:
        List of dicts with 'id', 'name', and 'description' keys.
    """
    return [
        {"id": preset_id, "name": preset.name, "description": preset.description}
        for preset_id, preset in PRESETS.items()
    ]


def get_preset(preset_id: str) -> PresetConfig:
    """Get a preset configuration by ID.

    Args:
        preset_id: The preset identifier (e.g., 'hacker-news')

    Returns:
        PresetConfig object

    Raises:
        KeyError: If preset_id is not found
    """
    if preset_id not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise KeyError(f"Unknown preset '{preset_id}'. Available: {available}")
    return PRESETS[preset_id]


def get_preset_schema_path(preset_id: str) -> Path:
    """Get the path to a preset's schema file.

    Args:
        preset_id: The preset identifier

    Returns:
        Path to the schema YAML file

    Raises:
        KeyError: If preset_id is not found
        FileNotFoundError: If schema file doesn't exist
    """
    preset = get_preset(preset_id)
    schema_path = get_schemas_dir() / preset.schema_file
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    return schema_path
