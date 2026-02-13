"""Presets module for common website scraping configurations."""

from ergane.presets.registry import (
    PRESETS,
    PresetConfig,
    get_preset,
    get_preset_schema_path,
    get_schemas_dir,
    list_presets,
)

__all__ = [
    "PRESETS",
    "PresetConfig",
    "get_preset",
    "get_preset_schema_path",
    "get_schemas_dir",
    "list_presets",
]
