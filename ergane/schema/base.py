"""Schema configuration classes for parsing Pydantic models."""

from dataclasses import dataclass, field
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined


@dataclass
class FieldConfig:
    """Configuration for a single field extracted from Pydantic model metadata."""

    name: str
    python_type: type[Any]
    selector: str | None = None
    attr: str | None = None
    coerce: bool = False
    default: Any = ...
    is_list: bool = False
    is_optional: bool = False
    inner_type: type[Any] | None = None
    is_nested_model: bool = False

    @property
    def is_auto_populated(self) -> bool:
        """Check if field is auto-populated (url, crawled_at)."""
        return self.selector is None and self.name in ("url", "crawled_at")


@dataclass
class SchemaConfig:
    """Configuration extracted from a Pydantic model for schema-based extraction."""

    model: type[BaseModel]
    fields: dict[str, FieldConfig] = field(default_factory=dict)

    @classmethod
    def from_model(cls, model: type[BaseModel]) -> "SchemaConfig":
        """Parse a Pydantic model to extract field configurations."""
        config = cls(model=model)

        for field_name, field_info in model.model_fields.items():
            field_config = cls._parse_field(field_name, field_info)
            config.fields[field_name] = field_config

        return config

    @classmethod
    def _parse_field(cls, name: str, field_info: FieldInfo) -> FieldConfig:
        """Parse a single Pydantic field into FieldConfig."""
        annotation = field_info.annotation
        python_type = annotation
        is_list = False
        is_optional = False
        inner_type = None
        is_nested_model = False

        # Handle Optional types (Union with None)
        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is type(None):
            python_type = type(None)
        elif _is_union_type(origin):
            # Check for Optional (Union[X, None])
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1 and type(None) in args:
                is_optional = True
                annotation = non_none_args[0]
                python_type = annotation
                origin = get_origin(annotation)
                args = get_args(annotation)

        # Handle list types
        if origin is list:
            is_list = True
            if args:
                inner_type = args[0]
                python_type = inner_type
                # Check if inner type is a nested model
                if isinstance(inner_type, type) and issubclass(inner_type, BaseModel):
                    is_nested_model = True

        # Check for nested BaseModel
        if isinstance(python_type, type) and issubclass(python_type, BaseModel):
            is_nested_model = True
            inner_type = python_type

        # Extract selector metadata from json_schema_extra
        selector = None
        attr = None
        coerce = False

        extra = field_info.json_schema_extra
        if extra and isinstance(extra, dict):
            selector = extra.get("selector")
            attr = extra.get("attr")
            coerce = extra.get("coerce", False)  # type: ignore[assignment]

        # Get default value - normalize PydanticUndefined to ... for consistency
        default = field_info.default
        if default is PydanticUndefined:
            default = ...
        elif default is None and field_info.default_factory is not None:
            default = ...  # Has factory, so required unless optional

        return FieldConfig(
            name=name,
            python_type=python_type,  # type: ignore[arg-type]
            selector=selector,  # type: ignore[arg-type]
            attr=attr,  # type: ignore[arg-type]
            coerce=coerce,
            default=default,
            is_list=is_list,
            is_optional=is_optional,
            inner_type=inner_type,
            is_nested_model=is_nested_model,
        )

    def get_selector_fields(self) -> dict[str, FieldConfig]:
        """Return only fields that have CSS selectors defined."""
        return {
            name: cfg for name, cfg in self.fields.items() if cfg.selector is not None
        }

    def get_auto_fields(self) -> dict[str, FieldConfig]:
        """Return fields that are auto-populated (url, crawled_at)."""
        return {name: cfg for name, cfg in self.fields.items() if cfg.is_auto_populated}


def _is_union_type(origin: Any) -> bool:
    """Check if origin is a Union type (typing.Union or types.UnionType)."""
    import types
    import typing

    if origin is typing.Union:
        return True
    # Python 3.10+ uses types.UnionType for X | Y syntax
    if hasattr(types, "UnionType") and origin is types.UnionType:
        return True
    return False
