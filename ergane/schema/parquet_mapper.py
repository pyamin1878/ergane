"""Maps Pydantic models to Polars schemas for native Parquet types."""

from datetime import datetime
from typing import Any

import polars as pl
from pydantic import BaseModel

from ergane.schema.base import SchemaConfig


class ParquetSchemaMapper:
    """Maps Pydantic model types to Polars data types for native Parquet storage."""

    # Mapping from Python types to Polars types
    TYPE_MAP: dict[type[Any], pl.DataType] = {
        str: pl.Utf8,  # type: ignore[dict-item]
        int: pl.Int64,  # type: ignore[dict-item]
        float: pl.Float64,  # type: ignore[dict-item]
        bool: pl.Boolean,  # type: ignore[dict-item]
        datetime: pl.Datetime("us"),
    }

    @classmethod
    def get_polars_schema(cls, model: type[BaseModel]) -> dict[str, pl.DataType]:
        """Generate a Polars schema from a Pydantic model.

        Args:
            model: Pydantic model class

        Returns:
            Dictionary mapping field names to Polars data types
        """
        schema_config = SchemaConfig.from_model(model)
        polars_schema: dict[str, pl.DataType] = {}

        for field_name, field_config in schema_config.fields.items():
            polars_type = cls._get_polars_type(field_config.python_type, field_config)
            polars_schema[field_name] = polars_type

        return polars_schema

    @classmethod
    def _get_polars_type(cls, python_type: type[Any], field_config: Any) -> pl.DataType:
        """Convert a Python type to the corresponding Polars type.

        Args:
            python_type: Python type annotation
            field_config: Field configuration for additional context

        Returns:
            Polars data type
        """
        # Handle list types
        if field_config.is_list:
            inner_type = cls._get_inner_polars_type(field_config.python_type)
            return pl.List(inner_type)

        # Handle nested Pydantic models
        if field_config.is_nested_model and field_config.inner_type is not None:
            return cls._get_struct_type(field_config.inner_type)

        # Basic type mapping
        return cls._get_inner_polars_type(python_type)

    @classmethod
    def _get_inner_polars_type(cls, python_type: type[Any]) -> pl.DataType:
        """Get Polars type for a non-container Python type.

        Args:
            python_type: Python type

        Returns:
            Polars data type
        """
        # Check if it's a nested model
        if isinstance(python_type, type) and issubclass(python_type, BaseModel):
            return cls._get_struct_type(python_type)

        return cls.TYPE_MAP.get(python_type, pl.Utf8)  # type: ignore[arg-type]

    @classmethod
    def _get_struct_type(cls, model: type[BaseModel]) -> pl.Struct:
        """Create a Polars Struct type from a Pydantic model.

        Args:
            model: Pydantic model class

        Returns:
            Polars Struct type
        """
        schema_config = SchemaConfig.from_model(model)
        fields: list[pl.Field] = []

        for field_name, field_config in schema_config.fields.items():
            polars_type = cls._get_polars_type(field_config.python_type, field_config)
            fields.append(pl.Field(field_name, polars_type))

        return pl.Struct(fields)

    @classmethod
    def model_to_dict(cls, instance: BaseModel) -> dict[str, Any]:
        """Convert a Pydantic model instance to a dict suitable for Polars.

        Handles nested models by converting them to dicts recursively.

        Args:
            instance: Pydantic model instance

        Returns:
            Dictionary with values ready for Polars DataFrame
        """
        result: dict[str, Any] = {}

        for field_name, value in instance.model_dump().items():
            if isinstance(value, BaseModel):
                result[field_name] = cls.model_to_dict(value)
            elif isinstance(value, list):
                result[field_name] = [
                    cls.model_to_dict(item) if isinstance(item, BaseModel) else item
                    for item in value
                ]
            else:
                result[field_name] = value

        return result

    @classmethod
    def models_to_dataframe(
        cls, instances: list[BaseModel], model: type[BaseModel] | None = None
    ) -> pl.DataFrame:
        """Convert list of Pydantic model instances to a Polars DataFrame.

        Args:
            instances: List of Pydantic model instances
            model: Optional model class for schema (inferred from instances if omitted)

        Returns:
            Polars DataFrame with native types
        """
        if not instances:
            if model is None:
                return pl.DataFrame()
            # Return empty DataFrame with correct schema
            return pl.DataFrame(schema=cls.get_polars_schema(model))

        # Infer model from first instance if not provided
        if model is None:
            model = type(instances[0])

        # Get schema
        polars_schema = cls.get_polars_schema(model)

        # Convert instances to dicts
        records = [cls.model_to_dict(inst) for inst in instances]

        # Create DataFrame with explicit schema
        return pl.DataFrame(records, schema=polars_schema)
