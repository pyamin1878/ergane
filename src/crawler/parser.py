from urllib.parse import urljoin, urlparse
from typing import Any

from selectolax.parser import HTMLParser

from src.models import CrawlResponse, ParsedItem


def extract_text(html: str) -> str:
    """Extract visible text content from HTML."""
    tree = HTMLParser(html)

    for tag in tree.css("script, style, noscript"):
        tag.decompose()

    return tree.text(separator=" ", strip=True)


def extract_title(html: str) -> str | None:
    """Extract the page title."""
    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    if title_node:
        return title_node.text(strip=True)
    return None


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract and normalize all links from HTML."""
    tree = HTMLParser(html)
    links: list[str] = []

    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href")
        if not href:
            continue

        href = href.strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)

        if parsed.scheme in ("http", "https"):
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            links.append(clean_url)

    return list(dict.fromkeys(links))


def extract_by_selector(html: str, selectors: dict[str, str]) -> dict[str, Any]:
    """Extract data using CSS selectors.

    Args:
        html: HTML content
        selectors: Mapping of field names to CSS selectors

    Returns:
        Extracted data for each selector
    """
    tree = HTMLParser(html)
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

    title = extract_title(response.content)
    text = extract_text(response.content)
    links = extract_links(response.content, response.url)

    extracted = {}
    if selectors:
        extracted = extract_by_selector(response.content, selectors)

    return ParsedItem(
        url=response.url,
        title=title,
        text=text,
        links=links,
        extracted_data=extracted,
        crawled_at=response.fetched_at,
    )
