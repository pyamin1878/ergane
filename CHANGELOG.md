# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-01-25

### Added

- **Custom Output Schemas**: Define Pydantic models with CSS selector mappings for type-safe extraction
- **Native Parquet Types**: Lists and structs stored as native Polars types instead of JSON strings
- **YAML Schema Support**: Load schemas from YAML files via `--schema` CLI option
- **Type Coercion**: Smart conversion of extracted strings to int, float, bool, datetime
  - Price extraction: `"$19.99"` -> `float(19.99)`
  - Number formatting: `"1,234"` -> `int(1234)`
  - Boolean values: `"yes"/"true"/"1"` -> `bool(True)`
- **Nested Model Support**: Extract complex hierarchical data with nested Pydantic models
- **Attribute Extraction**: Extract element attributes (href, src, data-*) via `attr` parameter

### New Modules

- `src/schema/` - Schema infrastructure for custom output types
  - `selector()` helper function for defining CSS selectors on Pydantic fields
  - `SchemaExtractor` for HTML to typed model extraction
  - `TypeCoercer` for string to typed value conversion
  - `ParquetSchemaMapper` for Pydantic to Polars schema mapping
  - `load_schema_from_yaml()` for YAML schema definitions

### Example Usage

```python
from pydantic import BaseModel
from datetime import datetime
from ergane.schema import selector

class ProductItem(BaseModel):
    url: str                    # Auto-populated
    crawled_at: datetime        # Auto-populated
    name: str = selector("h1.product-title")
    price: float = selector("span.price", coerce=True)
    tags: list[str] = selector("span.tag")
    image_url: str = selector("img.product", attr="src")
```

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
