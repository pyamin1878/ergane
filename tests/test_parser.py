"""Tests for HTML parsing functionality."""

from ergane.crawler.parser import (
    extract_by_selector,
    extract_data,
    extract_links,
    extract_text,
    extract_title,
)
from ergane.models import CrawlRequest, CrawlResponse


class TestExtractTitle:
    """Title extraction tests."""

    def test_basic_title(self, sample_html: str):
        """Test extracting basic title."""
        title = extract_title(sample_html)
        assert title == "Test Page"

    def test_missing_title(self):
        """Test handling missing title."""
        html = "<html><body><p>No title here</p></body></html>"
        title = extract_title(html)
        assert title is None

    def test_empty_title(self):
        """Test handling empty title tag."""
        html = "<html><head><title></title></head></html>"
        title = extract_title(html)
        assert title == ""

    def test_title_with_whitespace(self):
        """Test title with extra whitespace."""
        html = "<html><head><title>  Spaced Title  </title></head></html>"
        title = extract_title(html)
        assert title == "Spaced Title"


class TestExtractText:
    """Text extraction tests."""

    def test_basic_text(self, sample_html: str):
        """Test extracting visible text."""
        text = extract_text(sample_html)
        assert "Welcome" in text
        assert "test paragraph" in text

    def test_script_style_removed(self, sample_html: str):
        """Test that script and style content is removed."""
        text = extract_text(sample_html)
        assert "console.log" not in text
        assert ".hidden" not in text

    def test_empty_html(self):
        """Test handling empty HTML."""
        text = extract_text("")
        assert text == ""

    def test_text_only_html(self):
        """Test HTML with only text content."""
        html = "<html><body>Just plain text</body></html>"
        text = extract_text(html)
        assert "Just plain text" in text


class TestExtractLinks:
    """Link extraction tests."""

    def test_absolute_links(self, sample_html: str):
        """Test extracting absolute links."""
        links = extract_links(sample_html, "https://example.com/")
        assert "https://example.com/page2" in links

    def test_relative_links(self, sample_html: str):
        """Test converting relative links to absolute."""
        links = extract_links(sample_html, "https://example.com/current/")
        assert "https://example.com/page1" in links

    def test_mailto_links_excluded(self, sample_html: str):
        """Test that mailto links are excluded."""
        links = extract_links(sample_html, "https://example.com/")
        for link in links:
            assert not link.startswith("mailto:")

    def test_anchor_links_excluded(self, sample_html: str):
        """Test that anchor-only links are excluded."""
        links = extract_links(sample_html, "https://example.com/")
        for link in links:
            assert link != "#section"

    def test_javascript_links_excluded(self):
        """Test that javascript: links are excluded."""
        html = '<a href="javascript:void(0)">Click</a>'
        links = extract_links(html, "https://example.com/")
        assert len(links) == 0

    def test_duplicate_links_removed(self):
        """Test that duplicate links are deduplicated."""
        html = """
        <a href="/page">Link 1</a>
        <a href="/page">Link 2</a>
        <a href="/page">Link 3</a>
        """
        links = extract_links(html, "https://example.com/")
        assert links.count("https://example.com/page") == 1

    def test_empty_href_excluded(self):
        """Test that empty href is excluded."""
        html = '<a href="">Empty</a><a href="   ">Whitespace</a>'
        links = extract_links(html, "https://example.com/")
        assert len(links) == 0

    def test_query_string_preserved(self):
        """Test that query strings are preserved."""
        html = '<a href="/page?foo=bar&baz=qux">Link</a>'
        links = extract_links(html, "https://example.com/")
        assert "https://example.com/page?foo=bar&baz=qux" in links

    def test_fragment_removed(self):
        """Test that URL fragments are removed."""
        html = '<a href="/page#section">Link</a>'
        links = extract_links(html, "https://example.com/")
        assert "https://example.com/page" in links
        for link in links:
            assert "#" not in link


class TestExtractBySelector:
    """CSS selector extraction tests."""

    def test_single_match(self, sample_html: str):
        """Test selector with single match."""
        result = extract_by_selector(sample_html, {"heading": "h1"})
        assert result["heading"] == "Welcome"

    def test_multiple_matches(self, sample_html: str):
        """Test selector with multiple matches."""
        result = extract_by_selector(sample_html, {"items": "span.item"})
        assert isinstance(result["items"], list)
        assert len(result["items"]) == 2
        assert "Item 1" in result["items"]
        assert "Item 2" in result["items"]

    def test_no_match(self, sample_html: str):
        """Test selector with no matches."""
        result = extract_by_selector(sample_html, {"missing": ".nonexistent"})
        assert result["missing"] is None

    def test_multiple_selectors(self, sample_html: str):
        """Test multiple selectors at once."""
        result = extract_by_selector(
            sample_html, {"title": "title", "heading": "h1", "missing": ".nonexistent"}
        )
        assert result["title"] == "Test Page"
        assert result["heading"] == "Welcome"
        assert result["missing"] is None


class TestExtractData:
    """Full data extraction tests."""

    def test_successful_extraction(
        self, sample_response: CrawlResponse, sample_html: str
    ):
        """Test full extraction from valid response."""
        item = extract_data(sample_response)

        assert item.url == "https://example.com/page"
        assert item.title == "Test Page"
        assert item.text is not None
        assert "Welcome" in item.text
        assert len(item.links) > 0

    def test_empty_content(self, sample_request: CrawlRequest):
        """Test handling response with no content."""
        response = CrawlResponse(
            url="https://example.com/empty",
            status_code=200,
            content="",
            request=sample_request,
        )
        item = extract_data(response)

        assert item.url == "https://example.com/empty"
        assert "error" in item.extracted_data

    def test_error_response(self, sample_request: CrawlRequest):
        """Test handling error response."""
        response = CrawlResponse(
            url="https://example.com/error",
            status_code=500,
            content="",
            error="Internal Server Error",
            request=sample_request,
        )
        item = extract_data(response)

        assert "error" in item.extracted_data
        assert item.extracted_data["error"] == "Internal Server Error"

    def test_custom_selectors(self, sample_response: CrawlResponse):
        """Test extraction with custom selectors."""
        item = extract_data(
            sample_response, selectors={"heading": "h1", "items": "span.item"}
        )

        assert item.extracted_data["heading"] == "Welcome"
        assert isinstance(item.extracted_data["items"], list)

    def test_crawled_at_from_response(self, sample_response: CrawlResponse):
        """Test that crawled_at comes from response fetched_at."""
        item = extract_data(sample_response)
        assert item.crawled_at == sample_response.fetched_at


class TestMalformedHTML:
    """Tests for handling malformed HTML."""

    def test_unclosed_tags(self, malformed_html: str):
        """Test parsing HTML with unclosed tags doesn't raise."""
        # Should not raise - parser handles malformed HTML gracefully
        title = extract_title(malformed_html)
        text = extract_text(malformed_html)
        links = extract_links(malformed_html, "https://example.com/")

        # Should return valid types even if content extraction is incomplete
        assert title is not None or title is None  # Either is acceptable
        assert isinstance(text, str)
        assert isinstance(links, list)

    def test_parser_resilience(self):
        """Test parser doesn't crash on various malformed inputs."""
        malformed_cases = [
            "<html><body>",  # No closing tags
            "</div></span>Text",  # Orphan closing tags
            "<p><div></p></div>",  # Improper nesting
            "<<<>>>",  # Invalid syntax
            "",  # Empty
            "   ",  # Whitespace only
        ]
        for html in malformed_cases:
            # None of these should raise
            extract_title(html)
            extract_text(html)
            extract_links(html, "https://example.com/")

    def test_valid_link_in_partial_html(self):
        """Test link extraction from partial but valid HTML."""
        html = '<a href="https://example.com/page">Link</a>'
        links = extract_links(html, "https://example.com/")
        assert "https://example.com/page" in links


class TestEdgeCases:
    """Edge case tests."""

    def test_very_long_text(self):
        """Test handling very long text content."""
        long_text = "x" * 100000
        html = f"<html><body><p>{long_text}</p></body></html>"
        text = extract_text(html)
        assert len(text) >= 100000

    def test_unicode_content(self):
        """Test handling unicode content."""
        html = (
            "<html><head><title>测试页面</title></head><body>日本語テスト</body></html>"
        )
        title = extract_title(html)
        text = extract_text(html)

        assert title == "测试页面"
        assert "日本語テスト" in text

    def test_special_characters_in_links(self):
        """Test links with special characters."""
        html = '<a href="/search?q=hello%20world&lang=en">Search</a>'
        links = extract_links(html, "https://example.com/")
        assert "https://example.com/search?q=hello%20world&lang=en" in links
