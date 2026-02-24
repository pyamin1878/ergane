"""Load schema definitions from YAML files."""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, create_model

from ergane.schema.base import FieldConfig


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


def _create_field_config(field_name: str, field_cfg: dict[str, Any]) -> FieldConfig:
    """Create a FieldConfig directly from a YAML field definition.

    This is the primary path: YAML → FieldConfig, with no Pydantic roundtrip.

    Args:
        field_name: Name of the field
        field_cfg: Field configuration dict from YAML

    Returns:
        FieldConfig instance

    Raises:
        SchemaLoadError: If field configuration is invalid
    """
    type_str = field_cfg.get("type", "str")
    python_type, is_list = _parse_type(type_str)

    css = field_cfg.get("selector")
    if css is None:
        raise SchemaLoadError(f"Field '{field_name}' must have a 'selector' key")

    attr = field_cfg.get("attr")
    coerce = field_cfg.get("coerce", False)
    default = field_cfg.get("default", ...)

    # For list fields, python_type holds the element type
    # (mirrors SchemaConfig._parse_field behaviour)
    inner_type = python_type if is_list else None

    return FieldConfig(
        name=field_name,
        python_type=python_type,
        selector=css,
        attr=attr,
        coerce=coerce,
        default=default,
        is_list=is_list,
        # YAML schemas don't express Optional[X];
        # use default=None for optional behaviour instead
        is_optional=False,
        inner_type=inner_type,
        is_nested_model=False,
    )


def _build_model_from_config(config: dict) -> type[BaseModel]:
    """Build a Pydantic model from a parsed YAML config dict.

    Builds FieldConfig objects directly from YAML (the canonical representation),
    then derives the Pydantic model from them.  The FieldConfig dict is cached on
    the model class as ``__ergane_fields__`` so that SchemaConfig.from_model() can
    skip re-parsing json_schema_extra on every access.

    Args:
        config: Parsed YAML dictionary with 'name' and 'fields' keys.

    Returns:
        Dynamically created Pydantic model class with __ergane_fields__ attached.

    Raises:
        SchemaLoadError: If config is missing required keys or fields are invalid.
    """
    model_name = config.get("name", "DynamicSchema")

    fields_config = config.get("fields")
    if not fields_config or not isinstance(fields_config, dict):
        raise SchemaLoadError("YAML must have a 'fields' dictionary")

    # Step 1: Build FieldConfig objects directly — the canonical representation.
    field_configs: dict[str, FieldConfig] = {}
    field_configs["url"] = FieldConfig(name="url", python_type=str, selector=None)
    field_configs["crawled_at"] = FieldConfig(
        name="crawled_at", python_type=datetime, selector=None
    )

    for field_name, field_cfg in fields_config.items():
        if not isinstance(field_cfg, dict):
            raise SchemaLoadError(
                f"Field '{field_name}' must be a dictionary, got {type(field_cfg)}"
            )
        field_configs[field_name] = _create_field_config(field_name, field_cfg)

    # Step 2: Derive Pydantic field definitions from the FieldConfig objects.
    # json_schema_extra is kept so that the existing SchemaConfig slow path
    # still produces correct results if called on a model missing __ergane_fields__.
    pydantic_fields: dict[str, tuple[type[Any], Any]] = {}
    pydantic_fields["url"] = (str, ...)
    pydantic_fields["crawled_at"] = (datetime, ...)

    for fname, fconfig in field_configs.items():
        if fname in ("url", "crawled_at"):
            continue

        if fconfig.is_list:
            annotation = list[fconfig.python_type]  # type: ignore[valid-type]
        else:
            annotation = fconfig.python_type  # type: ignore[misc]

        field_info = Field(
            default=fconfig.default,
            json_schema_extra={
                "selector": fconfig.selector,
                "coerce": fconfig.coerce,
                "attr": fconfig.attr,
            },
        )
        pydantic_fields[fname] = (annotation, field_info)

    model = create_model(model_name, **pydantic_fields)  # type: ignore[call-overload, no-any-return]

    # Step 3: Cache FieldConfig objects on the model class.  SchemaConfig.from_model()
    # checks for this attribute first to avoid re-parsing json_schema_extra.
    model.__ergane_fields__ = field_configs  # type: ignore[attr-defined]

    return model  # type: ignore[return-value]


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
