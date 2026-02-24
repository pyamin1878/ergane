# MCP Server

Ergane includes a built-in [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that exposes its web scraping capabilities as tools for AI assistants like Claude. The server runs over stdio and is compatible with Claude Desktop, Claude Code, and any MCP-compatible client.

---

## Quick Start

1. Install Ergane with MCP support:

   ```bash
   pip install ergane[mcp]
   ```

2. Start the server:

   ```bash
   ergane mcp
   ```

3. Add it to your Claude configuration (see [Setup](#setup) below).

---

## Setup

Ergane's MCP server can be started in two ways:

```bash
ergane mcp            # via CLI subcommand
python -m ergane.mcp  # via Python module
```

Both start a stdio-based MCP server with the name `"ergane"`, built on `FastMCP` from the MCP SDK.

### Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ergane": {
      "command": "ergane",
      "args": ["mcp"]
    }
  }
}
```

### Claude Code

Add the following to `~/.claude/claude_code_config.json`:

```json
{
  "mcpServers": {
    "ergane": {
      "command": "ergane",
      "args": ["mcp"]
    }
  }
}
```

If you prefer automatic installation via `uvx`:

```json
{
  "mcpServers": {
    "ergane": {
      "command": "uvx",
      "args": ["--from", "ergane[mcp]", "ergane", "mcp"]
    }
  }
}
```

---

## Tools Reference

The server exposes four tools.

### `list_presets_tool`

List all available scraping presets with their details.

**Parameters:** None.

**Returns:** A JSON array of preset objects, each containing:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Preset identifier |
| `name` | `string` | Human-readable name |
| `description` | `string` | What the preset scrapes |
| `url` | `string` | Target URL |
| `fields` | `array[string]` | Available extraction fields |

**Example response:**

```json
[
  {
    "id": "hacker-news",
    "name": "Hacker News",
    "description": "Front page stories from news.ycombinator.com",
    "url": "https://news.ycombinator.com",
    "fields": ["title", "link", "score", "author", "comments"]
  }
]
```

---

### `extract_tool`

Extract structured data from a single web page using CSS selectors.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | `string` | Yes | -- | The URL to scrape |
| `selectors` | `object` | No | `null` | Map of field names to CSS selectors |
| `schema_yaml` | `string` | No | `null` | Full YAML schema definition (alternative to selectors) |
| `js` | `boolean` | No | `false` | Enable JavaScript rendering via Playwright |
| `js_wait` | `string` | No | `"networkidle"` | Playwright page wait strategy |

Provide either `selectors` or `schema_yaml`, not both. If neither is provided, returns a generic `ParsedItem`.

**Example** -- extracting with selectors:

```json
{
  "url": "https://example.com/product/123",
  "selectors": {
    "title": "h1.product-title",
    "price": "span.price",
    "description": "div.description p"
  }
}
```

**Example** -- extracting with a YAML schema:

```json
{
  "url": "https://example.com/product/123",
  "schema_yaml": "name: Product\nfields:\n  title:\n    selector: \"h1.product-title\"\n    type: str\n  price:\n    selector: \"span.price\"\n    type: float\n    coerce: true"
}
```

---

### `scrape_preset_tool`

Scrape a website using a built-in preset with zero configuration.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `preset` | `string` | Yes | -- | Preset name (e.g., `"hacker-news"`, `"quotes"`) |
| `max_pages` | `integer` | No | `5` | Maximum number of pages to scrape |
| `js` | `boolean` | No | `false` | Enable JavaScript rendering |
| `js_wait` | `string` | No | `"networkidle"` | Playwright wait strategy |

See the [Presets](#presets) section for the full list of available presets.

**Returns:** JSON array of extracted items, subject to [result truncation](#result-truncation).

**Example:**

```json
{
  "preset": "hacker-news",
  "max_pages": 2
}
```

---

### `crawl_tool`

Crawl one or more websites and extract structured data with full control over depth, concurrency, and output format.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `urls` | `array[string]` | Yes | -- | Starting URLs to crawl |
| `schema_yaml` | `string` | No | `null` | YAML schema for extraction |
| `max_pages` | `integer` | No | `10` | Maximum pages to crawl |
| `max_depth` | `integer` | No | `1` | Link-follow depth (0 = seed URLs only) |
| `concurrency` | `integer` | No | `5` | Number of concurrent requests |
| `output_format` | `string` | No | `"json"` | Output format: `"json"`, `"csv"`, or `"jsonl"` |
| `js` | `boolean` | No | `false` | Enable JavaScript rendering |
| `js_wait` | `string` | No | `"networkidle"` | Playwright wait strategy |

**Returns:** Extracted data as JSON array, CSV text, or JSONL text depending on `output_format`.

**Example** -- crawl with a YAML schema:

```json
{
  "urls": ["https://quotes.toscrape.com"],
  "schema_yaml": "name: Quote\nfields:\n  text:\n    selector: \"span.text\"\n    type: str\n  author:\n    selector: \"small.author\"\n    type: str",
  "max_pages": 3,
  "max_depth": 1,
  "output_format": "json"
}
```

---

## Schema YAML Format

The YAML schema defines the structure of data to extract from each page. It specifies a model name, a set of fields, and CSS selectors for each field.

### Full reference

```yaml
name: ProductItem
fields:
  name:
    selector: "h1.product-title"
    type: str
  price:
    selector: "span.price"
    type: float
    coerce: true
  tags:
    selector: "span.tag"
    type: list[str]
  image_url:
    selector: "img.product"
    attr: src
    type: str
```

### Field options

| Option | Description |
|--------|-------------|
| `selector` | CSS selector to locate the element |
| `type` | Data type for the extracted value |
| `attr` | HTML attribute to extract instead of text content (e.g., `src`, `href`) |
| `coerce` | When `true`, attempt type conversion (e.g., `"$12.99"` to `12.99`) |

### Supported types

| Type | Aliases |
|------|---------|
| `str` | `string` |
| `int` | `integer` |
| `float` | -- |
| `bool` | `boolean` |
| `datetime` | -- |
| `list[T]` | Where `T` is any of the above scalar types |

---

## Presets

Eight built-in presets are available for common scraping targets:

| Preset | Site | Fields |
|--------|------|--------|
| `hacker-news` | news.ycombinator.com | title, link, score, author, comments |
| `github-repos` | github.com/search | name, description, stars, language, link |
| `reddit` | old.reddit.com | title, subreddit, score, author, comments, link |
| `quotes` | quotes.toscrape.com | quote, author, tags |
| `amazon-products` | amazon.com | title, price, rating, reviews, link |
| `ebay-listings` | ebay.com | title, price, condition, shipping, link |
| `wikipedia-articles` | en.wikipedia.org | title, link |
| `bbc-news` | bbc.com/news | title, summary, link |

Use `list_presets_tool` at runtime to get the full details including descriptions and target URLs.

---

## Resources

Each preset is also exposed as an MCP resource using the URI scheme `preset://{name}`. For example:

- `preset://hacker-news`
- `preset://quotes`
- `preset://bbc-news`

Reading a resource returns a JSON object with the preset's `id`, `name`, `description`, `url`, and `fields`.

---

## JavaScript Rendering

All four tools accept `js` and `js_wait` parameters for scraping JavaScript-rendered pages.

### Installation

JavaScript rendering requires Playwright, which is included in the `js` extra:

```bash
pip install ergane[js]
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `js` | `boolean` | `false` | Set to `true` to render the page with a headless browser before extraction |
| `js_wait` | `string` | `"networkidle"` | When to consider the page loaded |

### Wait strategies

| Strategy | Description |
|----------|-------------|
| `"networkidle"` | Wait until there are no network connections for at least 500ms (default) |
| `"domcontentloaded"` | Wait until the `DOMContentLoaded` event fires |
| `"load"` | Wait until the `load` event fires |

### Example

```json
{
  "url": "https://example.com/spa-page",
  "selectors": {"title": "h1", "content": "div.main"},
  "js": true,
  "js_wait": "networkidle"
}
```

---

## Error Handling

When a tool encounters an error, it returns a JSON object with `error` and `error_code` fields:

```json
{
  "error": "Preset 'nonexistent' not found",
  "error_code": "INVALID_PRESET"
}
```

### Error codes

| Code | Description |
|------|-------------|
| `FETCH_ERROR` | Network or HTTP problem (failed fetch, empty response) |
| `INVALID_PRESET` | Unknown preset name passed to `scrape_preset_tool` |
| `SCHEMA_ERROR` | YAML schema failed to parse |
| `INVALID_PARAMS` | Invalid parameter values |
| `INTERNAL_ERROR` | Unexpected exception |

---

## Result Truncation

To keep responses manageable for AI assistants, results are capped at **50 items** (`MAX_RESULT_ITEMS = 50`).

When the total number of items exceeds 50, results are wrapped in an envelope:

```json
{
  "items": [],
  "total": 127,
  "truncated": true
}
```

The `items` array contains the first 50 results, `total` reflects the actual count, and `truncated` is set to `true`.

When results contain 50 or fewer items, they are returned as a plain JSON array without the envelope.

---

## See Also

- [CLI Usage](cli.md) -- command-line interface reference
- [Python Library](python-library.md) -- using Ergane as a Python library
