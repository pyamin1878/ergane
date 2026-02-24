"""MCP prompt definitions for Ergane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.fastmcp.prompts.base import AssistantMessage, UserMessage

from ergane.presets import PRESETS

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def build_schema_prompt(url: str) -> list:
    """Guide the user through building a YAML extraction schema for a website.

    Args:
        url: The target website URL to build a schema for.
    """
    return [
        UserMessage(
            f"I want to extract structured data from this website: {url}\n\n"
            "Help me build an Ergane YAML extraction schema. First, use the "
            "extract_tool to fetch the page without any selectors to see its "
            "structure, then help me identify the right CSS selectors for the "
            "data I want to extract."
        ),
        AssistantMessage(
            f"I'll help you build a YAML schema for {url}. Let me start by "
            "fetching the page to understand its structure.\n\n"
            "An Ergane YAML schema looks like this:\n\n"
            "```yaml\n"
            "name: MySchema\n"
            "fields:\n"
            "  title:\n"
            '    selector: "h1"\n'
            "    type: str\n"
            "  price:\n"
            '    selector: "span.price"\n'
            "    type: float\n"
            "    coerce: true\n"
            "  tags:\n"
            '    selector: "div.tags a"\n'
            "    type: list[str]\n"
            "  image_url:\n"
            '    selector: "img.product"\n'
            "    attr: src\n"
            "    type: str\n"
            "```\n\n"
            "**Supported types:** str, int, float, bool, datetime, "
            "list[str], list[int], list[float]\n\n"
            "**Key options:** `selector` (CSS), `type`, `coerce` "
            "(auto-convert), `attr` (HTML attribute), `default`\n\n"
            f"Let me fetch {url} now to see what data is available."
        ),
    ]


def choose_preset_prompt(task: str) -> list:
    """Help choose the right built-in scraping preset.

    Args:
        task: Description of what data you want to scrape.
    """
    preset_list = "\n".join(
        f"- **{pid}**: {p.name} -- {p.description} "
        f"(URL: {p.start_urls[0]})"
        for pid, p in PRESETS.items()
    )
    return [
        UserMessage(
            f"I want to scrape the following: {task}\n\n"
            "Which Ergane preset should I use, or do I need a custom schema?"
        ),
        AssistantMessage(
            "Here are the available Ergane presets:\n\n"
            f"{preset_list}\n\n"
            f'Based on your task ("{task}"), let me recommend the best '
            "approach. If none of these presets match, I can help you build "
            "a custom YAML schema using the build-schema prompt instead."
        ),
    ]


def plan_crawl_prompt(url: str, goal: str) -> list:
    """Help design an optimal crawl strategy for a website.

    Args:
        url: The starting URL to crawl.
        goal: What data you want to collect and how much.
    """
    return [
        UserMessage(
            f"I want to crawl {url} with this goal: {goal}\n\n"
            "Help me choose the right crawl settings: depth, max pages, "
            "rate limit, concurrency, and whether I need JavaScript rendering."
        ),
        AssistantMessage(
            f"I'll help you design a crawl strategy for {url}.\n\n"
            "Here are the key parameters to consider:\n\n"
            "| Parameter | Default | Description |\n"
            "|-----------|---------|-------------|\n"
            "| `max_pages` | 10 | Total pages to fetch |\n"
            "| `max_depth` | 1 | How deep to follow links (0 = seed only) |\n"
            "| `concurrency` | 5 | Parallel requests |\n"
            "| `rate_limit` | 5.0 | Max requests/second |\n"
            "| `timeout` | 60.0 | Per-request timeout (seconds) |\n"
            "| `same_domain` | true | Stay on the same domain |\n"
            "| `ignore_robots` | false | Skip robots.txt checks |\n"
            "| `js` | false | Enable JavaScript rendering |\n"
            "| `proxy` | null | Proxy URL |\n"
            "| `headers` | null | Custom HTTP headers |\n\n"
            "**Tips:**\n"
            "- For single-page extraction, use `extract_tool` instead\n"
            "- Start with `max_depth=0` to test, then increase\n"
            "- Use `rate_limit=1.0` for sites that throttle aggressively\n"
            "- Enable `js=true` only for SPAs (adds significant overhead)\n"
            "- Set `same_domain=false` carefully -- it can explode crawl "
            "scope\n\n"
            f'Given your goal ("{goal}"), let me suggest settings for {url}.'
        ),
    ]


def register_prompts(mcp: FastMCP) -> None:
    """Register all Ergane prompts with the MCP server."""
    mcp.prompt(
        name="build-schema",
        title="Build Extraction Schema",
        description=(
            "Guides you through building a YAML schema for extracting "
            "data from a website."
        ),
    )(build_schema_prompt)
    mcp.prompt(
        name="choose-preset",
        title="Choose a Scraping Preset",
        description=(
            "Helps pick the right built-in preset for your scraping needs."
        ),
    )(choose_preset_prompt)
    mcp.prompt(
        name="plan-crawl",
        title="Plan a Crawl Strategy",
        description=(
            "Helps design an optimal crawl strategy with appropriate settings."
        ),
    )(plan_crawl_prompt)
