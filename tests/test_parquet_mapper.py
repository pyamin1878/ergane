"""Tests for Pydantic to Polars schema mapping."""

from datetime import datetime, timezone

import polars as pl
import pytest
from pydantic import BaseModel

from ergane.schema import ParquetSchemaMapper, selector


class TestTypeMapping:
    """Tests for Python to Polars type mapping."""

    def test_string_type(self):
        """String fields map to Utf8."""

        class TestModel(BaseModel):
            name: str = selector("h1")

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["name"] == pl.Utf8

    def test_int_type(self):
        """Integer fields map to Int64."""

        class TestModel(BaseModel):
            count: int = selector("span.count")

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["count"] == pl.Int64

    def test_float_type(self):
        """Float fields map to Float64."""

        class TestModel(BaseModel):
            price: float = selector("span.price")

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["price"] == pl.Float64

    def test_bool_type(self):
        """Boolean fields map to Boolean."""

        class TestModel(BaseModel):
            active: bool = selector("span.status")

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["active"] == pl.Boolean

    def test_datetime_type(self):
        """Datetime fields map to Datetime."""

        class TestModel(BaseModel):
            crawled_at: datetime

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["crawled_at"] == pl.Datetime("us")


class TestListMapping:
    """Tests for list type mapping."""

    def test_list_of_strings(self):
        """List of strings maps to List(Utf8)."""

        class TestModel(BaseModel):
            tags: list[str] = selector("span.tag")

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["tags"] == pl.List(pl.Utf8)

    def test_list_of_ints(self):
        """List of integers maps to List(Int64)."""

        class TestModel(BaseModel):
            counts: list[int] = selector("span.count")

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["counts"] == pl.List(pl.Int64)

    def test_list_of_floats(self):
        """List of floats maps to List(Float64)."""

        class TestModel(BaseModel):
            prices: list[float] = selector("span.price")

        schema = ParquetSchemaMapper.get_polars_schema(TestModel)
        assert schema["prices"] == pl.List(pl.Float64)


class TestStructMapping:
    """Tests for nested model (struct) type mapping."""

    def test_nested_model_to_struct(self):
        """Nested Pydantic model maps to Struct."""

        class Address(BaseModel):
            street: str = selector("span.street")
            city: str = selector("span.city")

        class Person(BaseModel):
            name: str = selector("h1")
            address: Address = selector("div.address")

        schema = ParquetSchemaMapper.get_polars_schema(Person)

        assert schema["name"] == pl.Utf8
        assert isinstance(schema["address"], pl.Struct)

        # Check struct fields
        struct_type = schema["address"]
        field_names = [f.name for f in struct_type.fields]
        assert "street" in field_names
        assert "city" in field_names

    def test_list_of_nested_models(self):
        """List of nested models maps to List(Struct)."""

        class Review(BaseModel):
            author: str = selector("span.author")
            rating: int = selector("span.rating")

        class Product(BaseModel):
            name: str = selector("h1")
            reviews: list[Review] = selector("div.review")

        schema = ParquetSchemaMapper.get_polars_schema(Product)

        assert schema["name"] == pl.Utf8
        assert isinstance(schema["reviews"], pl.List)

        # Check inner type is Struct
        inner_type = schema["reviews"].inner
        assert isinstance(inner_type, pl.Struct)


class TestModelToDict:
    """Tests for model instance to dict conversion."""

    def test_simple_model_to_dict(self):
        """Simple model converts to dict."""

        class TestModel(BaseModel):
            name: str
            count: int

        instance = TestModel(name="Test", count=42)
        result = ParquetSchemaMapper.model_to_dict(instance)

        assert result == {"name": "Test", "count": 42}

    def test_nested_model_to_dict(self):
        """Nested model converts to nested dict."""

        class Address(BaseModel):
            city: str

        class Person(BaseModel):
            name: str
            address: Address

        instance = Person(name="John", address=Address(city="NYC"))
        result = ParquetSchemaMapper.model_to_dict(instance)

        assert result == {"name": "John", "address": {"city": "NYC"}}

    def test_list_values_preserved(self):
        """List values are preserved in conversion."""

        class TestModel(BaseModel):
            tags: list[str]

        instance = TestModel(tags=["a", "b", "c"])
        result = ParquetSchemaMapper.model_to_dict(instance)

        assert result == {"tags": ["a", "b", "c"]}


class TestModelsToDataframe:
    """Tests for converting model instances to DataFrames."""

    def test_simple_models_to_dataframe(self):
        """Convert list of simple models to DataFrame."""

        class TestModel(BaseModel):
            name: str
            value: int

        instances = [
            TestModel(name="A", value=1),
            TestModel(name="B", value=2),
        ]
        df = ParquetSchemaMapper.models_to_dataframe(instances)

        assert len(df) == 2
        assert df.schema["name"] == pl.Utf8
        assert df.schema["value"] == pl.Int64
        assert df["name"].to_list() == ["A", "B"]
        assert df["value"].to_list() == [1, 2]

    def test_empty_list_with_model(self):
        """Empty list with model type returns empty DataFrame with schema."""

        class TestModel(BaseModel):
            name: str
            value: int

        df = ParquetSchemaMapper.models_to_dataframe([], TestModel)

        assert len(df) == 0
        assert df.schema["name"] == pl.Utf8
        assert df.schema["value"] == pl.Int64

    def test_empty_list_without_model(self):
        """Empty list without model type returns empty DataFrame."""
        df = ParquetSchemaMapper.models_to_dataframe([])
        assert len(df) == 0

    def test_list_fields_native_type(self):
        """List fields use native Polars List type."""

        class TestModel(BaseModel):
            tags: list[str]

        instances = [
            TestModel(tags=["a", "b"]),
            TestModel(tags=["c"]),
        ]
        df = ParquetSchemaMapper.models_to_dataframe(instances)

        assert df.schema["tags"] == pl.List(pl.Utf8)
        assert df["tags"].to_list() == [["a", "b"], ["c"]]

    def test_datetime_fields(self):
        """Datetime fields are handled correctly."""

        class TestModel(BaseModel):
            timestamp: datetime

        fixed_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        instances = [TestModel(timestamp=fixed_time)]
        df = ParquetSchemaMapper.models_to_dataframe(instances)

        assert df.schema["timestamp"] == pl.Datetime("us")

    def test_nested_models_as_structs(self):
        """Nested models are converted to Polars Structs."""

        class Address(BaseModel):
            city: str
            zip_code: str

        class Person(BaseModel):
            name: str
            address: Address

        instances = [
            Person(name="John", address=Address(city="NYC", zip_code="10001")),
        ]
        df = ParquetSchemaMapper.models_to_dataframe(instances)

        assert df.schema["name"] == pl.Utf8
        assert isinstance(df.schema["address"], pl.Struct)

        # Verify the data
        assert df["name"].to_list() == ["John"]
        # Access struct fields
        address_data = df["address"].to_list()[0]
        assert address_data["city"] == "NYC"
        assert address_data["zip_code"] == "10001"


class TestCompleteSchema:
    """Tests for complete schema mapping with all features."""

    def test_complete_product_schema(self):
        """Test complete schema mapping for a product model."""

        class Product(BaseModel):
            url: str
            crawled_at: datetime
            name: str = selector("h1")
            price: float = selector("span.price", coerce=True)
            tags: list[str] = selector("span.tag")
            in_stock: bool = selector("span.stock")

        schema = ParquetSchemaMapper.get_polars_schema(Product)

        assert schema["url"] == pl.Utf8
        assert schema["crawled_at"] == pl.Datetime("us")
        assert schema["name"] == pl.Utf8
        assert schema["price"] == pl.Float64
        assert schema["tags"] == pl.List(pl.Utf8)
        assert schema["in_stock"] == pl.Boolean
