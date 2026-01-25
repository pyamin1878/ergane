from typing import Any
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from src.models import CrawlResponse, ParsedItem


def _extract_text_from_tree(tree: HTMLParser) -> str:
    """Extract visible text content from parsed HTML tree."""
    for tag in tree.css("script, style, noscript"):
        tag.decompose()

    return tree.text(separator=" ", strip=True)


def _extract_title_from_tree(tree: HTMLParser) -> str | None:
    """Extract the page title from parsed HTML tree."""
    title_node = tree.css_first("title")
    if title_node:
        return title_node.text(strip=True)
    return None


def _extract_links_from_tree(tree: HTMLParser, base_url: str) -> list[str]:
    """Extract and normalize all links from parsed HTML tree."""
    links: list[str] = []

    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href")
        if not href:
            continue

        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)

        if parsed.scheme in ("http", "https"):
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            links.append(clean_url)

    return list(dict.fromkeys(links))


def _extract_by_selector_from_tree(
    tree: HTMLParser, selectors: dict[str, str]
) -> dict[str, Any]:
    """Extract data using CSS selectors from parsed HTML tree.

    Args:
        tree: Parsed HTML tree
        selectors: Mapping of field names to CSS selectors

    Returns:
        Extracted data for each selector
    """
    result: dict[str, Any] = {}

    for field, selector in selectors.items():
        nodes = tree.css(selector)
        if not nodes:
            result[field] = None
        elif len(nodes) == 1:
            result[field] = nodes[0].text(strip=True)
        else:
            result[field] = [n.text(strip=True) for n in nodes]

    return result


# Public API functions that maintain backwards compatibility
def extract_text(html: str) -> str:
    """Extract visible text content from HTML."""
    tree = HTMLParser(html)
    return _extract_text_from_tree(tree)


def extract_title(html: str) -> str | None:
    """Extract the page title."""
    tree = HTMLParser(html)
    return _extract_title_from_tree(tree)


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract and normalize all links from HTML."""
    tree = HTMLParser(html)
    return _extract_links_from_tree(tree, base_url)


def extract_by_selector(html: str, selectors: dict[str, str]) -> dict[str, Any]:
    """Extract data using CSS selectors.

    Args:
        html: HTML content
        selectors: Mapping of field names to CSS selectors

    Returns:
        Extracted data for each selector
    """
    tree = HTMLParser(html)
    return _extract_by_selector_from_tree(tree, selectors)


def extract_data(
    response: CrawlResponse,
    selectors: dict[str, str] | None = None,
) -> ParsedItem:
    """Parse a crawl response into structured data.

    Args:
        response: The crawl response to parse
        selectors: Optional CSS selectors for custom extraction

    Returns:
        Parsed item with extracted data
    """
    if not response.content:
        return ParsedItem(
            url=response.url,
            extracted_data={"error": response.error or "No content"},
        )

    # Parse HTML once and reuse tree for all extractions
    tree = HTMLParser(response.content)

    # Extract title before decomposing script/style tags
    title = _extract_title_from_tree(tree)

    # Extract links before decomposing tags
    links = _extract_links_from_tree(tree, response.url)

    # Extract custom selectors before decomposing tags
    extracted = {}
    if selectors:
        extracted = _extract_by_selector_from_tree(tree, selectors)

    # Extract text (this decomposes script/style tags, so do last)
    text = _extract_text_from_tree(tree)

    return ParsedItem(
        url=response.url,
        title=title,
        text=text,
        links=links,
        extracted_data=extracted,
        crawled_at=response.fetched_at,
    )
