"""Load schema definitions from YAML files."""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo


class SchemaLoadError(Exception):
    """Raised when schema loading fails."""

    pass


# Mapping from YAML type names to Python types
TYPE_MAP: dict[str, type[Any]] = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "bool": bool,
    "boolean": bool,
    "datetime": datetime,
}


def _parse_type(type_str: str) -> tuple[type[Any], bool]:
    """Parse a type string into Python type and list flag.

    Args:
        type_str: Type string like "str", "int", "list[str]", etc.

    Returns:
        Tuple of (python_type, is_list)

    Raises:
        SchemaLoadError: If type string is invalid
    """
    type_str = type_str.strip()

    # Check for list type
    if type_str.startswith("list[") and type_str.endswith("]"):
        inner_type_str = type_str[5:-1].strip()
        inner_type = TYPE_MAP.get(inner_type_str)
        if inner_type is None:
            raise SchemaLoadError(f"Unknown type in list: {inner_type_str}")
        return inner_type, True

    # Simple type
    python_type = TYPE_MAP.get(type_str)
    if python_type is None:
        raise SchemaLoadError(f"Unknown type: {type_str}")
    return python_type, False


def _create_field(field_config: dict[str, Any]) -> tuple[type[Any], FieldInfo]:
    """Create a Pydantic field from YAML field configuration.

    Args:
        field_config: Field configuration dict from YAML

    Returns:
        Tuple of (annotation, field_info)

    Raises:
        SchemaLoadError: If field configuration is invalid
    """
    # Get type
    type_str = field_config.get("type", "str")
    python_type, is_list = _parse_type(type_str)

    # Get selector configuration
    css = field_config.get("selector")
    if css is None:
        raise SchemaLoadError("Field must have a 'selector' key")

    attr = field_config.get("attr")
    coerce = field_config.get("coerce", False)
    default = field_config.get("default", ...)

    # Create field with selector metadata (same as selector() helper)
    field_info = Field(
        default=default,
        json_schema_extra={"selector": css, "coerce": coerce, "attr": attr},
    )

    # Determine annotation
    if is_list:
        annotation = list[python_type]  # type: ignore[valid-type]
    else:
        annotation = python_type  # type: ignore[misc]

    return annotation, field_info


def _build_model_from_config(config: dict) -> type[BaseModel]:
    """Build a Pydantic model from a parsed YAML config dict.

    Args:
        config: Parsed YAML dictionary with 'name' and 'fields' keys.

    Returns:
        Dynamically created Pydantic model class.

    Raises:
        SchemaLoadError: If config is missing required keys or fields are invalid.
    """
    model_name = config.get("name", "DynamicSchema")

    fields_config = config.get("fields")
    if not fields_config or not isinstance(fields_config, dict):
        raise SchemaLoadError("YAML must have a 'fields' dictionary")

    field_definitions: dict[str, tuple[type[Any], Any]] = {}
    field_definitions["url"] = (str, ...)
    field_definitions["crawled_at"] = (datetime, ...)

    for field_name, field_cfg in fields_config.items():
        if not isinstance(field_cfg, dict):
            raise SchemaLoadError(
                f"Field '{field_name}' must be a dictionary, got {type(field_cfg)}"
            )
        annotation, field_info = _create_field(field_cfg)
        field_definitions[field_name] = (annotation, field_info)

    return create_model(model_name, **field_definitions)  # type: ignore[call-overload, no-any-return]


def load_schema_from_yaml(path: str | Path) -> type[BaseModel]:
    """Load a Pydantic model from a YAML schema definition.

    YAML format:
    ```yaml
    name: ProductItem
    fields:
      title:
        selector: "h1"
        type: str
      price:
        selector: "span.price"
        type: float
        coerce: true
      tags:
        selector: "span.tag"
        type: list[str]
      image:
        selector: "img.product"
        attr: src
        type: str
    ```

    The model automatically includes `url` (str) and `crawled_at` (datetime) fields.

    Args:
        path: Path to YAML file

    Returns:
        Dynamically created Pydantic model class

    Raises:
        SchemaLoadError: If YAML is invalid or missing required keys
    """
    path = Path(path)

    if not path.exists():
        raise SchemaLoadError(f"Schema file not found: {path}")

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise SchemaLoadError(f"Invalid YAML: {e}") from e

    if not isinstance(config, dict):
        raise SchemaLoadError("YAML must be a dictionary")

    return _build_model_from_config(config)


def load_schema_from_string(yaml_content: str) -> type[BaseModel]:
    """Load a Pydantic model from a YAML string.

    Args:
        yaml_content: YAML content as string

    Returns:
        Dynamically created Pydantic model class

    Raises:
        SchemaLoadError: If YAML is invalid
    """
    try:
        config = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise SchemaLoadError(f"Invalid YAML: {e}") from e

    if not isinstance(config, dict):
        raise SchemaLoadError("YAML must be a dictionary")

    return _build_model_from_config(config)
