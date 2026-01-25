# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-24

### Added

- Initial release of Ergane web crawler
- Async HTTP/2 client using httpx for fast concurrent connections
- Per-domain rate limiting with token bucket algorithm
- Exponential backoff retry logic (max 3 attempts)
- robots.txt compliance (enabled by default)
- Fast HTML parsing with selectolax (16x faster than BeautifulSoup)
- Priority queue scheduler with URL deduplication
- Parquet output format via polars for efficient storage
- Graceful shutdown handling for SIGINT/SIGTERM
- CLI interface with configurable options:
  - Multiple start URLs support
  - Configurable concurrency and rate limits
  - Depth limiting
  - Same-domain or cross-domain crawling
  - Custom output paths
