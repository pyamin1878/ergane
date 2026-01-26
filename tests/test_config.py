"""Tests for config file loading."""

from pathlib import Path

import pytest
import yaml

from src.config import load_config, merge_config


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Fixture for temporary config file path."""
    return tmp_path / ".ergane.yaml"


@pytest.fixture
def sample_config() -> dict:
    """Fixture for a sample config dictionary."""
    return {
        "crawler": {
            "rate_limit": 5.0,
            "concurrency": 15,
            "timeout": 45.0,
            "respect_robots_txt": False,
            "user_agent": "CustomBot/1.0",
            "proxy": "http://localhost:8080",
        },
        "defaults": {
            "max_pages": 200,
            "max_depth": 5,
            "same_domain": True,
            "output_format": "csv",
        },
        "logging": {
            "level": "DEBUG",
            "file": "crawl.log",
        },
    }


def test_load_config_explicit_path(config_path: Path, sample_config: dict):
    """Test loading config from an explicit path."""
    with open(config_path, "w") as f:
        yaml.dump(sample_config, f)

    loaded = load_config(config_path)
    assert loaded["crawler"]["rate_limit"] == 5.0
    assert loaded["defaults"]["max_pages"] == 200
    assert loaded["logging"]["level"] == "DEBUG"


def test_load_config_nonexistent():
    """Test loading from nonexistent file returns empty dict."""
    result = load_config(Path("/nonexistent/path.yaml"))
    assert result == {}


def test_load_config_empty_file(config_path: Path):
    """Test loading an empty config file returns empty dict."""
    config_path.write_text("")
    result = load_config(config_path)
    assert result == {}


def test_merge_config_file_only(sample_config: dict):
    """Test merging with only file config."""
    cli_args = {}
    result = merge_config(sample_config, cli_args)

    assert result["rate_limit"] == 5.0
    assert result["concurrency"] == 15
    assert result["max_pages"] == 200
    assert result["level"] == "DEBUG"


def test_merge_config_cli_overrides(sample_config: dict):
    """Test CLI args override file config."""
    cli_args = {
        "rate_limit": 20.0,
        "max_pages": 500,
        "level": "WARNING",
    }
    result = merge_config(sample_config, cli_args)

    # CLI values should override
    assert result["rate_limit"] == 20.0
    assert result["max_pages"] == 500
    assert result["level"] == "WARNING"
    # File values should remain for non-overridden keys
    assert result["concurrency"] == 15
    assert result["timeout"] == 45.0


def test_merge_config_cli_none_ignored(sample_config: dict):
    """Test that None CLI values don't override file config."""
    cli_args = {
        "rate_limit": None,
        "max_pages": None,
    }
    result = merge_config(sample_config, cli_args)

    # File values should remain when CLI is None
    assert result["rate_limit"] == 5.0
    assert result["max_pages"] == 200


def test_merge_config_empty_file():
    """Test merging with empty file config."""
    file_config = {}
    cli_args = {
        "rate_limit": 10.0,
        "max_pages": 100,
    }
    result = merge_config(file_config, cli_args)

    assert result["rate_limit"] == 10.0
    assert result["max_pages"] == 100


def test_merge_config_partial_sections():
    """Test merging with only some sections present."""
    file_config = {
        "crawler": {
            "rate_limit": 8.0,
        },
        # No defaults or logging sections
    }
    cli_args = {"max_pages": 50}
    result = merge_config(file_config, cli_args)

    assert result["rate_limit"] == 8.0
    assert result["max_pages"] == 50
