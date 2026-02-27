#!/usr/bin/env python
"""Ergane performance benchmark.

Baseline (2026-02-26, post-optimizations, concurrency=20, 200 pages):
  pages_crawled          200
  items_extracted        200
  elapsed_s              1.545
  pages_per_sec          129.5
  items_per_sec          129.5
  peak_memory_mb         5.18

Spins up a local HTTP server with synthetic link graph, runs a timed crawl,
and prints throughput metrics. Run with:

    uv run python benchmarks/run.py [--pages N] [--concurrency N]
"""

from __future__ import annotations

import asyncio
import sys
import time
import tracemalloc
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


# ---------------------------------------------------------------------------
# Synthetic site generator
# ---------------------------------------------------------------------------

def _build_pages(n: int) -> dict[str, bytes]:
    """Build N interlinked HTML pages for crawling."""
    pages: dict[str, bytes] = {}
    for i in range(n):
        links = "".join(
            f'<a href="/page/{j}">page {j}</a> '
            for j in range(max(0, i - 2), min(n, i + 3))
            if j != i
        )
        html = (
            f"<html><head><title>Page {i}</title></head>"
            f"<body><h1>Page {i}</h1>{links}</body></html>"
        ).encode()
        pages[f"/page/{i}"] = html
    # index page links to all pages so depth-1 discovery reaches the full graph
    index_links = "".join(f'<a href="/page/{i}">page {i}</a> ' for i in range(n))
    pages["/"] = (
        f"<html><head><title>Index</title></head>"
        f"<body><h1>Index</h1>{index_links}</body></html>"
    ).encode()
    return pages


class _BenchHandler(BaseHTTPRequestHandler):
    pages: dict[str, bytes] = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/robots.txt":
            self.send_response(404)
            self.end_headers()
            return
        body = self.pages.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

async def run_benchmark(n_pages: int = 200, concurrency: int = 20) -> dict:
    from ergane.crawler.engine import Crawler

    _BenchHandler.pages = _build_pages(n_pages)
    server = HTTPServer(("127.0.0.1", 0), _BenchHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/"
    tracemalloc.start()

    start = time.monotonic()
    items = 0
    async with Crawler(
        urls=[url],
        max_pages=n_pages,
        max_depth=2,
        concurrency=concurrency,
        rate_limit=1000.0,
        same_domain=True,
        respect_robots_txt=False,
    ) as crawler:
        async for _ in crawler.stream():
            items += 1
    elapsed = time.monotonic() - start

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    server.shutdown()

    pages_crawled = crawler.pages_crawled
    return {
        "pages_crawled": pages_crawled,
        "items_extracted": items,
        "elapsed_s": round(elapsed, 3),
        "pages_per_sec": round(pages_crawled / max(elapsed, 0.001), 1),
        "items_per_sec": round(items / max(elapsed, 0.001), 1),
        "peak_memory_mb": round(peak / 1024 / 1024, 2),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ergane benchmark")
    parser.add_argument("--pages", type=int, default=200, help="Pages to crawl")
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    print(f"Benchmarking: {args.pages} pages, concurrency={args.concurrency}")
    results = asyncio.run(run_benchmark(args.pages, args.concurrency))

    print("\nResults:")
    for k, v in results.items():
        print(f"  {k:<22} {v}")


if __name__ == "__main__":
    main()
