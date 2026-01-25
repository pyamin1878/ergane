#!/usr/bin/env python3
"""Benchmark comparing Selectolax vs BeautifulSoup for HTML parsing operations.

This script compares parsing performance between Arachne's selectolax-based parser
and BeautifulSoup with lxml backend across various HTML sizes and operations.
"""

import gc
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
from bs4 import BeautifulSoup
from selectolax.parser import HTMLParser

# Sample pages for benchmarking (various sizes)
SAMPLE_URLS = {
    "small": "https://example.com",  # ~1KB
    "medium": "https://httpbin.org/html",  # ~3KB simple page
    "large": "https://news.ycombinator.com",  # ~30KB with many links
}

CACHE_DIR = Path(__file__).parent / ".cache"
ITERATIONS = 1000

# HTTP client with proper headers
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ArachneBenchmark/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}


@dataclass
class BenchmarkResult:
    """Result of a single benchmark operation."""

    name: str
    selectolax_ms: float
    bs4_ms: float

    @property
    def speedup(self) -> float:
        """Calculate speedup factor (BS4 time / Selectolax time)."""
        if self.selectolax_ms == 0:
            return float("inf")
        return self.bs4_ms / self.selectolax_ms


def fetch_sample_html(name: str, url: str) -> str:
    """Fetch and cache sample HTML for benchmarking."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{name}.html"

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    print(f"Fetching {name} sample from {url}...")
    response = httpx.get(url, headers=HTTP_HEADERS, follow_redirects=True, timeout=30)
    response.raise_for_status()
    html = response.text

    cache_file.write_text(html, encoding="utf-8")
    return html


def generate_synthetic_html(size: str) -> str:
    """Generate synthetic HTML for benchmarking when fetching fails."""
    if size == "small":
        return """<!DOCTYPE html>
<html><head><title>Small Test Page</title></head>
<body><h1>Hello</h1><p>Simple content.</p>
<a href="/link1">Link 1</a><a href="/link2">Link 2</a>
</body></html>"""

    if size == "medium":
        links = "\n".join(f'<a href="/page{i}">Link {i}</a>' for i in range(100))
        paragraphs = "\n".join(f"<p>Paragraph {i} with some text content.</p>" for i in range(50))
        return f"""<!DOCTYPE html>
<html><head><title>Medium Test Page</title>
<script>console.log('test');</script>
<style>body {{ margin: 0; }}</style>
</head>
<body><h1>Medium Page</h1>
{paragraphs}
<nav>{links}</nav>
</body></html>"""

    # Large
    links = "\n".join(f'<a href="/page{i}">Link {i}</a>' for i in range(500))
    paragraphs = "\n".join(
        f"<p>Paragraph {i} with longer text content that simulates real articles.</p>"
        for i in range(200)
    )
    divs = "\n".join(f'<div class="item"><span>Item {i}</span></div>' for i in range(300))
    return f"""<!DOCTYPE html>
<html><head><title>Large Test Page</title>
<script>var x = 1; function test() {{ return x; }}</script>
<style>body {{ margin: 0; }} .item {{ padding: 10px; }}</style>
</head>
<body><h1>Large Page</h1>
{paragraphs}
<nav>{links}</nav>
<section>{divs}</section>
</body></html>"""


def benchmark_operation(
    func: Callable[[], None],
    iterations: int = ITERATIONS,
) -> float:
    """Run a function multiple times and return average time in milliseconds."""
    gc.collect()
    gc.disable()

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        times.append(end - start)

    gc.enable()

    # Use median to reduce outlier impact
    return statistics.median(times) * 1000


# Selectolax operations
def selectolax_parse(html: str) -> HTMLParser:
    """Parse HTML with selectolax."""
    return HTMLParser(html)


def selectolax_title(html: str) -> str | None:
    """Extract title with selectolax."""
    tree = HTMLParser(html)
    title = tree.css_first("title")
    return title.text(strip=True) if title else None


def selectolax_links(html: str) -> list[str]:
    """Extract all links with selectolax."""
    tree = HTMLParser(html)
    links = []
    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href")
        if href:
            links.append(href)
    return links


def selectolax_text(html: str) -> str:
    """Extract text with selectolax (removing scripts/styles)."""
    tree = HTMLParser(html)
    for tag in tree.css("script, style, noscript"):
        tag.decompose()
    return tree.text(separator=" ", strip=True)


def selectolax_selector(html: str, selector: str) -> list[str]:
    """Query by CSS selector with selectolax."""
    tree = HTMLParser(html)
    return [node.text(strip=True) for node in tree.css(selector)]


# BeautifulSoup operations
def bs4_parse(html: str) -> BeautifulSoup:
    """Parse HTML with BeautifulSoup + lxml."""
    return BeautifulSoup(html, "lxml")


def bs4_title(html: str) -> str | None:
    """Extract title with BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.find("title")
    return title.get_text(strip=True) if title else None


def bs4_links(html: str) -> list[str]:
    """Extract all links with BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")
    links = []
    for anchor in soup.find_all("a", href=True):
        links.append(anchor["href"])
    return links


def bs4_text(html: str) -> str:
    """Extract text with BeautifulSoup (removing scripts/styles)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def bs4_selector(html: str, selector: str) -> list[str]:
    """Query by CSS selector with BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")
    return [elem.get_text(strip=True) for elem in soup.select(selector)]


def run_benchmarks(samples: dict[str, str]) -> list[BenchmarkResult]:
    """Run all benchmarks and return results."""
    results = []

    for size_name, html in samples.items():
        html_kb = len(html.encode("utf-8")) / 1024
        print(f"\nBenchmarking {size_name} HTML ({html_kb:.1f} KB)...")

        # Parse benchmark
        print(f"  Parse ({ITERATIONS} iterations)...")
        selectolax_time = benchmark_operation(lambda h=html: selectolax_parse(h))
        bs4_time = benchmark_operation(lambda h=html: bs4_parse(h))
        results.append(BenchmarkResult(f"Parse ({size_name})", selectolax_time, bs4_time))

        # Title extraction
        print(f"  Extract title ({ITERATIONS} iterations)...")
        selectolax_time = benchmark_operation(lambda h=html: selectolax_title(h))
        bs4_time = benchmark_operation(lambda h=html: bs4_title(h))
        results.append(
            BenchmarkResult(f"Title ({size_name})", selectolax_time, bs4_time)
        )

        # Link extraction
        print(f"  Extract links ({ITERATIONS} iterations)...")
        selectolax_time = benchmark_operation(lambda h=html: selectolax_links(h))
        bs4_time = benchmark_operation(lambda h=html: bs4_links(h))
        results.append(
            BenchmarkResult(f"Links ({size_name})", selectolax_time, bs4_time)
        )

        # Text extraction
        print(f"  Extract text ({ITERATIONS} iterations)...")
        selectolax_time = benchmark_operation(lambda h=html: selectolax_text(h))
        bs4_time = benchmark_operation(lambda h=html: bs4_text(h))
        results.append(BenchmarkResult(f"Text ({size_name})", selectolax_time, bs4_time))

        # CSS selector query
        print(f"  CSS selector ({ITERATIONS} iterations)...")
        selector = "p"
        selectolax_time = benchmark_operation(
            lambda h=html, s=selector: selectolax_selector(h, s)
        )
        bs4_time = benchmark_operation(lambda h=html, s=selector: bs4_selector(h, s))
        results.append(
            BenchmarkResult(f"Selector ({size_name})", selectolax_time, bs4_time)
        )

    return results


def print_results(results: list[BenchmarkResult]) -> None:
    """Print benchmark results as a formatted table."""
    # Calculate column widths
    name_width = max(len(r.name) for r in results)
    name_width = max(name_width, len("Operation"))

    header = (
        f"{'Operation':<{name_width}} │ "
        f"{'Selectolax':>12} │ "
        f"{'BS4 + lxml':>12} │ "
        f"{'Speedup':>8}"
    )
    separator = "─" * name_width + "─┼─" + "─" * 12 + "─┼─" + "─" * 12 + "─┼─" + "─" * 8

    print("\n" + "=" * len(header))
    print(f"Benchmark Results ({ITERATIONS} iterations each)")
    print("=" * len(header))
    print(header)
    print(separator)

    for result in results:
        speedup_str = f"{result.speedup:.1f}x"
        print(
            f"{result.name:<{name_width}} │ "
            f"{result.selectolax_ms:>10.3f}ms │ "
            f"{result.bs4_ms:>10.3f}ms │ "
            f"{speedup_str:>8}"
        )

    print(separator)

    # Summary statistics
    avg_speedup = statistics.mean(r.speedup for r in results)
    print(f"\nAverage speedup: {avg_speedup:.1f}x faster with Selectolax")


def main() -> None:
    """Run the benchmark suite."""
    print("HTML Parser Benchmark: Selectolax vs BeautifulSoup")
    print("-" * 50)

    # Fetch sample HTML (with synthetic fallback)
    samples = {}
    for name, url in SAMPLE_URLS.items():
        try:
            samples[name] = fetch_sample_html(name, url)
        except Exception as e:
            print(f"Warning: Could not fetch {name} sample: {e}")
            print(f"  Using synthetic {name} HTML instead...")
            samples[name] = generate_synthetic_html(name)

    if not samples:
        print("Error: No samples available for benchmarking")
        return

    # Run benchmarks
    results = run_benchmarks(samples)

    # Print results
    print_results(results)


if __name__ == "__main__":
    main()
