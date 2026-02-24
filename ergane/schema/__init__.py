"""Schema module for custom Pydantic output schemas.

This module provides tools for defining custom extraction schemas using Pydantic
models with CSS selector metadata.

Example usage:
    from pydantic import BaseModel
    from ergane.schema import selector

    class ProductItem(BaseModel):
        url: str                    # Auto-populated
        crawled_at: datetime        # Auto-populated

        name: str = selector("h1.product-title")
        price: float = selector("span.price", coerce=True)
        tags: list[str] = selector("span.tag")
        image_url: str = selector("img.product", attr="src")
"""

from typing import Any

from pydantic import Field

from ergane.schema.base import FieldConfig, SchemaConfig
from ergane.schema.coercion import CoercionError, TypeCoercer
from ergane.schema.extractor import ExtractionError, FieldResult, SchemaExtractor
from ergane.schema.parquet_mapper import ParquetSchemaMapper
from ergane.schema.yaml_loader import SchemaLoadError, load_schema_from_yaml

__all__ = [
    "selector",
    "FieldConfig",
    "SchemaConfig",
    "TypeCoercer",
    "CoercionError",
    "SchemaExtractor",
    "ExtractionError",
    "FieldResult",
    "ParquetSchemaMapper",
    "SchemaLoadError",
    "load_schema_from_yaml",
]


def selector(
    css: str,
    *,
    coerce: bool = False,
    attr: str | None = None,
    default: Any = ...,
) -> Any:
    """Define a field that extracts data using a CSS selector.

    Args:
        css: CSS selector string to match elements
        coerce: If True, use aggressive type coercion (e.g., extract "$19.99" -> 19.99)
        attr: Extract this attribute instead of text content (e.g., "href", "src")
        default: Default value if selector matches nothing (use ... for required fields)

    Returns:
        Pydantic Field with selector metadata

    Example:
        class Product(BaseModel):
            name: str = selector("h1.title")
            price: float = selector("span.price", coerce=True)
            image: str = selector("img.main", attr="src")
            rating: float = selector("span.rating", default=0.0)
    """
    return Field(
        default=default,
        json_schema_extra={"selector": css, "coerce": coerce, "attr": attr},
    )
