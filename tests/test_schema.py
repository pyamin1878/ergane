"""Tests for schema parsing functionality."""

from datetime import datetime
from typing import Optional

import pytest
from pydantic import BaseModel

from ergane.schema import FieldConfig, SchemaConfig, selector


class TestSelectorHelper:
    """Tests for the selector() helper function."""

    def test_basic_selector(self):
        """Basic selector creates correct field metadata."""

        class TestModel(BaseModel):
            name: str = selector("h1.title")

        config = SchemaConfig.from_model(TestModel)
        field = config.fields["name"]

        assert field.selector == "h1.title"
        assert field.coerce is False
        assert field.attr is None

    def test_selector_with_coerce(self):
        """Selector with coerce flag is parsed correctly."""

        class TestModel(BaseModel):
            price: float = selector("span.price", coerce=True)

        config = SchemaConfig.from_model(TestModel)
        field = config.fields["price"]

        assert field.selector == "span.price"
        assert field.coerce is True

    def test_selector_with_attr(self):
        """Selector with attr is parsed correctly."""

        class TestModel(BaseModel):
            image: str = selector("img.main", attr="src")

        config = SchemaConfig.from_model(TestModel)
        field = config.fields["image"]

        assert field.selector == "img.main"
        assert field.attr == "src"

    def test_selector_with_default(self):
        """Selector with default value is parsed correctly."""

        class TestModel(BaseModel):
            rating: float = selector("span.rating", default=0.0)

        config = SchemaConfig.from_model(TestModel)
        field = config.fields["rating"]

        assert field.default == 0.0


class TestSchemaConfig:
    """Tests for SchemaConfig parsing."""

    def test_simple_model(self):
        """Simple model is parsed correctly."""

        class SimpleModel(BaseModel):
            title: str = selector("h1")
            content: str = selector("div.content")

        config = SchemaConfig.from_model(SimpleModel)

        assert len(config.fields) == 2
        assert config.fields["title"].selector == "h1"
        assert config.fields["content"].selector == "div.content"

    def test_auto_populated_fields(self):
        """Fields without selectors for url/crawled_at are auto-populated."""

        class ItemModel(BaseModel):
            url: str
            crawled_at: datetime
            title: str = selector("h1")

        config = SchemaConfig.from_model(ItemModel)

        assert config.fields["url"].is_auto_populated
        assert config.fields["crawled_at"].is_auto_populated
        assert not config.fields["title"].is_auto_populated

    def test_list_field_detection(self):
        """List fields are detected correctly."""

        class ListModel(BaseModel):
            tags: list[str] = selector("span.tag")

        config = SchemaConfig.from_model(ListModel)
        field = config.fields["tags"]

        assert field.is_list
        assert field.inner_type is str

    def test_optional_field_detection(self):
        """Optional fields are detected correctly."""

        class OptionalModel(BaseModel):
            subtitle: str | None = selector("h2", default=None)

        config = SchemaConfig.from_model(OptionalModel)
        field = config.fields["subtitle"]

        assert field.is_optional

    def test_type_detection(self):
        """Python types are detected correctly."""

        class TypesModel(BaseModel):
            name: str = selector("h1")
            count: int = selector("span.count")
            price: float = selector("span.price")
            active: bool = selector("span.status")

        config = SchemaConfig.from_model(TypesModel)

        assert config.fields["name"].python_type is str
        assert config.fields["count"].python_type is int
        assert config.fields["price"].python_type is float
        assert config.fields["active"].python_type is bool

    def test_get_selector_fields(self):
        """get_selector_fields returns only fields with selectors."""

        class MixedModel(BaseModel):
            url: str  # Auto-populated, no selector
            title: str = selector("h1")
            content: str = selector("div.content")

        config = SchemaConfig.from_model(MixedModel)
        selector_fields = config.get_selector_fields()

        assert len(selector_fields) == 2
        assert "title" in selector_fields
        assert "content" in selector_fields
        assert "url" not in selector_fields

    def test_get_auto_fields(self):
        """get_auto_fields returns auto-populated fields."""

        class ItemModel(BaseModel):
            url: str
            crawled_at: datetime
            title: str = selector("h1")

        config = SchemaConfig.from_model(ItemModel)
        auto_fields = config.get_auto_fields()

        assert len(auto_fields) == 2
        assert "url" in auto_fields
        assert "crawled_at" in auto_fields
        assert "title" not in auto_fields


class TestNestedModels:
    """Tests for nested Pydantic model detection."""

    def test_nested_model_detection(self):
        """Nested BaseModel fields are detected."""

        class Address(BaseModel):
            street: str = selector("span.street")
            city: str = selector("span.city")

        class Person(BaseModel):
            name: str = selector("h1")
            address: Address = selector("div.address")

        config = SchemaConfig.from_model(Person)
        address_field = config.fields["address"]

        assert address_field.is_nested_model
        assert address_field.inner_type is Address

    def test_list_of_nested_models(self):
        """List of nested models is detected correctly."""

        class Review(BaseModel):
            author: str = selector("span.author")
            text: str = selector("p.text")

        class Product(BaseModel):
            name: str = selector("h1")
            reviews: list[Review] = selector("div.review")

        config = SchemaConfig.from_model(Product)
        reviews_field = config.fields["reviews"]

        assert reviews_field.is_list
        assert reviews_field.is_nested_model
        assert reviews_field.inner_type is Review


class TestFieldConfig:
    """Tests for FieldConfig dataclass."""

    def test_is_auto_populated_url(self):
        """url field without selector is auto-populated."""
        field = FieldConfig(name="url", python_type=str, selector=None)
        assert field.is_auto_populated

    def test_is_auto_populated_crawled_at(self):
        """crawled_at field without selector is auto-populated."""
        field = FieldConfig(name="crawled_at", python_type=datetime, selector=None)
        assert field.is_auto_populated

    def test_is_not_auto_populated_with_selector(self):
        """Field with selector is not auto-populated even if named url."""
        field = FieldConfig(name="url", python_type=str, selector="a.link")
        assert not field.is_auto_populated

    def test_is_not_auto_populated_other_field(self):
        """Regular field without selector is not auto-populated."""
        field = FieldConfig(name="title", python_type=str, selector=None)
        assert not field.is_auto_populated
