"""Tests for the preset system."""

from pathlib import Path

import pytest

from ergane.presets import (
    PRESETS,
    PresetConfig,
    get_preset,
    get_preset_schema_path,
    get_schemas_dir,
    list_presets,
)
from ergane.schema import load_schema_from_yaml


class TestPresetRegistry:
    """Test preset registry functions."""

    def test_list_presets_returns_all_presets(self):
        """Test that list_presets returns all available presets."""
        presets = list_presets()

        assert len(presets) == len(PRESETS)
        preset_ids = [p["id"] for p in presets]
        assert "hacker-news" in preset_ids
        assert "github-repos" in preset_ids
        assert "reddit" in preset_ids
        assert "quotes" in preset_ids

    def test_list_presets_structure(self):
        """Test that list_presets returns correct structure."""
        presets = list_presets()

        for preset in presets:
            assert "id" in preset
            assert "name" in preset
            assert "description" in preset
            assert isinstance(preset["id"], str)
            assert isinstance(preset["name"], str)
            assert isinstance(preset["description"], str)

    def test_get_preset_valid(self):
        """Test getting a valid preset."""
        preset = get_preset("hacker-news")

        assert isinstance(preset, PresetConfig)
        assert preset.name == "Hacker News"
        assert "news.ycombinator.com" in preset.start_urls[0]
        assert preset.schema_file == "hacker_news.yaml"
        assert "max_pages" in preset.defaults
        assert "max_depth" in preset.defaults

    def test_get_preset_invalid(self):
        """Test getting an invalid preset raises KeyError."""
        with pytest.raises(KeyError) as exc_info:
            get_preset("nonexistent-preset")

        assert "nonexistent-preset" in str(exc_info.value)
        assert "Available:" in str(exc_info.value)

    def test_get_schemas_dir(self):
        """Test that schemas directory exists."""
        schemas_dir = get_schemas_dir()

        assert schemas_dir.exists()
        assert schemas_dir.is_dir()

    def test_get_preset_schema_path_valid(self):
        """Test getting schema path for valid preset."""
        schema_path = get_preset_schema_path("hacker-news")

        assert schema_path.exists()
        assert schema_path.suffix == ".yaml"
        assert schema_path.name == "hacker_news.yaml"

    def test_get_preset_schema_path_invalid_preset(self):
        """Test getting schema path for invalid preset."""
        with pytest.raises(KeyError):
            get_preset_schema_path("nonexistent")


class TestPresetConfigs:
    """Test individual preset configurations."""

    @pytest.mark.parametrize(
        "preset_id",
        ["hacker-news", "github-repos", "reddit", "quotes"],
    )
    def test_preset_has_required_fields(self, preset_id: str):
        """Test that all presets have required fields."""
        preset = get_preset(preset_id)

        assert preset.name
        assert preset.description
        assert len(preset.start_urls) > 0
        assert preset.schema_file
        assert isinstance(preset.defaults, dict)

    @pytest.mark.parametrize(
        "preset_id",
        ["hacker-news", "github-repos", "reddit", "quotes"],
    )
    def test_preset_schema_exists(self, preset_id: str):
        """Test that all preset schema files exist."""
        schema_path = get_preset_schema_path(preset_id)
        assert schema_path.exists()

    @pytest.mark.parametrize(
        "preset_id",
        ["hacker-news", "github-repos", "reddit", "quotes"],
    )
    def test_preset_schema_loads(self, preset_id: str):
        """Test that all preset schemas load correctly."""
        schema_path = get_preset_schema_path(preset_id)
        schema = load_schema_from_yaml(schema_path)

        assert schema is not None
        # Schema should be a dynamically created BaseModel class
        assert hasattr(schema, "model_fields")


class TestPresetDefaults:
    """Test preset default values."""

    def test_hacker_news_defaults(self):
        """Test Hacker News preset defaults."""
        preset = get_preset("hacker-news")
        assert preset.defaults["max_pages"] == 30
        assert preset.defaults["max_depth"] == 1

    def test_github_repos_defaults(self):
        """Test GitHub repos preset defaults."""
        preset = get_preset("github-repos")
        assert preset.defaults["max_pages"] == 50
        assert preset.defaults["max_depth"] == 1

    def test_reddit_defaults(self):
        """Test Reddit preset defaults."""
        preset = get_preset("reddit")
        assert preset.defaults["max_pages"] == 50
        assert preset.defaults["max_depth"] == 1

    def test_quotes_defaults(self):
        """Test Quotes preset defaults."""
        preset = get_preset("quotes")
        assert preset.defaults["max_pages"] == 10
        assert preset.defaults["max_depth"] == 2


class TestSchemaContent:
    """Test that schema files have expected content."""

    def test_hacker_news_schema_fields(self):
        """Test Hacker News schema has expected fields."""
        schema_path = get_preset_schema_path("hacker-news")
        schema = load_schema_from_yaml(schema_path)

        # Get field names from the model
        field_names = set(schema.model_fields.keys())
        expected_fields = {"title", "link", "score", "author", "comments"}
        assert expected_fields.issubset(field_names)

    def test_quotes_schema_fields(self):
        """Test Quotes schema has expected fields."""
        schema_path = get_preset_schema_path("quotes")
        schema = load_schema_from_yaml(schema_path)

        field_names = set(schema.model_fields.keys())
        expected_fields = {"quote", "author", "tags"}
        assert expected_fields.issubset(field_names)
