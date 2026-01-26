"""Tests for schema-based HTML extraction."""

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from src.schema import ExtractionError, SchemaExtractor, selector


class TestBasicExtraction:
    """Tests for basic field extraction."""

    def test_extract_single_text_field(self):
        """Extract single text field from HTML."""

        class TestModel(BaseModel):
            title: str = selector("h1")

        html = "<html><body><h1>Hello World</h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "Hello World"

    def test_extract_multiple_fields(self):
        """Extract multiple fields from HTML."""

        class TestModel(BaseModel):
            title: str = selector("h1")
            content: str = selector("p.content")

        html = """
        <html><body>
            <h1>Title</h1>
            <p class="content">Content text</p>
        </body></html>
        """
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "Title"
        assert result.content == "Content text"

    def test_extract_with_whitespace(self):
        """Whitespace is stripped from extracted values."""

        class TestModel(BaseModel):
            title: str = selector("h1")

        html = "<html><body><h1>  Spaced Title  </h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "Spaced Title"


class TestAutoPopulatedFields:
    """Tests for auto-populated fields (url, crawled_at)."""

    def test_url_auto_populated(self):
        """url field is auto-populated from extraction call."""

        class TestModel(BaseModel):
            url: str
            title: str = selector("h1")

        html = "<html><body><h1>Test</h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com/page")

        assert result.url == "https://example.com/page"

    def test_crawled_at_auto_populated(self):
        """crawled_at field is auto-populated from extraction call."""

        class TestModel(BaseModel):
            crawled_at: datetime
            title: str = selector("h1")

        html = "<html><body><h1>Test</h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)

        fixed_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = extractor.extract(
            html, url="https://example.com", crawled_at=fixed_time
        )

        assert result.crawled_at == fixed_time

    def test_crawled_at_defaults_to_now(self):
        """crawled_at defaults to current time if not provided."""

        class TestModel(BaseModel):
            crawled_at: datetime
            title: str = selector("h1")

        html = "<html><body><h1>Test</h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)

        before = datetime.now(timezone.utc)
        result = extractor.extract(html, url="https://example.com")
        after = datetime.now(timezone.utc)

        assert before <= result.crawled_at <= after


class TestAttributeExtraction:
    """Tests for extracting attribute values."""

    def test_extract_href_attribute(self):
        """Extract href attribute from link."""

        class TestModel(BaseModel):
            link: str = selector("a.main-link", attr="href")

        html = '<a class="main-link" href="https://example.com/page">Click</a>'
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.link == "https://example.com/page"

    def test_extract_src_attribute(self):
        """Extract src attribute from image."""

        class TestModel(BaseModel):
            image: str = selector("img.product", attr="src")

        html = '<img class="product" src="/images/product.jpg" alt="Product">'
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.image == "/images/product.jpg"

    def test_extract_data_attribute(self):
        """Extract custom data attribute."""

        class TestModel(BaseModel):
            product_id: str = selector("div.product", attr="data-id")

        html = '<div class="product" data-id="12345">Product</div>'
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.product_id == "12345"


class TestListExtraction:
    """Tests for extracting lists of values."""

    def test_extract_list_of_strings(self):
        """Extract list of text values."""

        class TestModel(BaseModel):
            tags: list[str] = selector("span.tag")

        html = """
        <div>
            <span class="tag">Python</span>
            <span class="tag">Web</span>
            <span class="tag">Scraping</span>
        </div>
        """
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.tags == ["Python", "Web", "Scraping"]

    def test_extract_list_of_attributes(self):
        """Extract list of attribute values."""

        class TestModel(BaseModel):
            links: list[str] = selector("a", attr="href")

        html = """
        <nav>
            <a href="/page1">Page 1</a>
            <a href="/page2">Page 2</a>
            <a href="/page3">Page 3</a>
        </nav>
        """
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.links == ["/page1", "/page2", "/page3"]

    def test_empty_list_when_no_matches(self):
        """Return empty list when selector matches nothing."""

        class TestModel(BaseModel):
            tags: list[str] = selector("span.tag")

        html = "<div>No tags here</div>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.tags == []


class TestTypeCoercion:
    """Tests for type coercion during extraction."""

    def test_coerce_integer(self):
        """Extract and coerce integer value."""

        class TestModel(BaseModel):
            count: int = selector("span.count", coerce=True)

        html = '<span class="count">42 items</span>'
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.count == 42

    def test_coerce_float_price(self):
        """Extract and coerce float from price string."""

        class TestModel(BaseModel):
            price: float = selector("span.price", coerce=True)

        html = '<span class="price">$19.99</span>'
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.price == 19.99

    def test_coerce_list_of_prices(self):
        """Extract and coerce list of prices."""

        class TestModel(BaseModel):
            prices: list[float] = selector("span.price", coerce=True)

        html = """
        <div>
            <span class="price">$10.00</span>
            <span class="price">$25.50</span>
            <span class="price">$99.99</span>
        </div>
        """
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.prices == [10.0, 25.5, 99.99]


class TestOptionalFields:
    """Tests for optional field handling."""

    def test_optional_field_returns_none(self):
        """Optional field returns None when not found."""

        class TestModel(BaseModel):
            title: str = selector("h1")
            subtitle: str | None = selector("h2", default=None)

        html = "<html><body><h1>Title Only</h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "Title Only"
        assert result.subtitle is None

    def test_default_value_used(self):
        """Default value is used when field not found."""

        class TestModel(BaseModel):
            rating: float = selector("span.rating", default=0.0)

        html = "<div>No rating</div>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.rating == 0.0


class TestRequiredFields:
    """Tests for required field extraction errors."""

    def test_missing_required_field_raises(self):
        """Missing required field raises ExtractionError."""

        class TestModel(BaseModel):
            title: str = selector("h1")

        html = "<div>No h1 here</div>"
        extractor = SchemaExtractor.from_model(TestModel)

        with pytest.raises(ExtractionError) as exc:
            extractor.extract(html, url="https://example.com")

        assert "title" in str(exc.value)
        assert "h1" in str(exc.value)


class TestNestedModels:
    """Tests for nested Pydantic model extraction."""

    def test_extract_nested_model(self):
        """Extract nested model from HTML."""

        class Author(BaseModel):
            name: str = selector("span.name")
            email: str = selector("span.email")

        class Article(BaseModel):
            title: str = selector("h1")
            author: Author = selector("div.author")

        html = """
        <html><body>
            <h1>Article Title</h1>
            <div class="author">
                <span class="name">John Doe</span>
                <span class="email">john@example.com</span>
            </div>
        </body></html>
        """
        extractor = SchemaExtractor.from_model(Article)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "Article Title"
        assert result.author.name == "John Doe"
        assert result.author.email == "john@example.com"

    def test_extract_list_of_nested_models(self):
        """Extract list of nested models from HTML."""

        class Review(BaseModel):
            author: str = selector("span.author")
            text: str = selector("p.text")

        class Product(BaseModel):
            name: str = selector("h1")
            reviews: list[Review] = selector("div.review")

        html = """
        <html><body>
            <h1>Product Name</h1>
            <div class="review">
                <span class="author">Alice</span>
                <p class="text">Great product!</p>
            </div>
            <div class="review">
                <span class="author">Bob</span>
                <p class="text">Works well.</p>
            </div>
        </body></html>
        """
        extractor = SchemaExtractor.from_model(Product)
        result = extractor.extract(html, url="https://example.com")

        assert result.name == "Product Name"
        assert len(result.reviews) == 2
        assert result.reviews[0].author == "Alice"
        assert result.reviews[0].text == "Great product!"
        assert result.reviews[1].author == "Bob"
        assert result.reviews[1].text == "Works well."


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_html(self):
        """Handle empty HTML content."""

        class TestModel(BaseModel):
            title: str = selector("h1", default="No Title")

        html = ""
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "No Title"

    def test_malformed_html(self):
        """Handle malformed HTML gracefully."""

        class TestModel(BaseModel):
            title: str = selector("h1")

        # Malformed HTML - parser handles gracefully but may include nested content
        html = "<html><body><h1>Title</h1><p>Content"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "Title"

    def test_unicode_content(self):
        """Handle unicode content correctly."""

        class TestModel(BaseModel):
            title: str = selector("h1")

        html = "<html><body><h1>日本語テスト</h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "日本語テスト"

    def test_empty_text_node(self):
        """Handle empty text nodes."""

        class TestModel(BaseModel):
            title: str = selector("h1", default="Empty")

        html = "<html><body><h1></h1></body></html>"
        extractor = SchemaExtractor.from_model(TestModel)
        result = extractor.extract(html, url="https://example.com")

        assert result.title == "Empty"


class TestFromModel:
    """Tests for SchemaExtractor.from_model factory."""

    def test_from_model_creates_extractor(self):
        """from_model creates a working extractor."""

        class TestModel(BaseModel):
            title: str = selector("h1")

        extractor = SchemaExtractor.from_model(TestModel)
        assert extractor.schema_config.model is TestModel

    def test_from_model_parses_all_fields(self):
        """from_model parses all model fields."""

        class TestModel(BaseModel):
            url: str
            title: str = selector("h1")
            content: str = selector("div.content")

        extractor = SchemaExtractor.from_model(TestModel)
        assert len(extractor.schema_config.fields) == 3
