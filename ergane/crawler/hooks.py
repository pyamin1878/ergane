"""Hook system for intercepting crawl requests and responses.

Hooks allow users to inspect and modify requests before they're fetched,
and responses after they're received. Returning None from a hook skips
the request or discards the response.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ergane.logging import get_logger
from ergane.models import CrawlRequest, CrawlResponse

_logger = get_logger()


@runtime_checkable
class CrawlHook(Protocol):
    """Protocol for crawl hooks.

    Implement on_request and/or on_response to intercept the crawl pipeline.
    Return the (possibly modified) object to continue, or None to skip/discard.
    """

    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None: ...
    async def on_response(self, response: CrawlResponse) -> CrawlResponse | None: ...


class BaseHook:
    """Convenience base class — override only what you need."""

    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None:
        return request

    async def on_response(self, response: CrawlResponse) -> CrawlResponse | None:
        return response


class LoggingHook(BaseHook):
    """Logs requests and responses at DEBUG level."""

    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None:
        _logger.debug("Hook: requesting %s (depth=%d)", request.url, request.depth)
        return request

    async def on_response(self, response: CrawlResponse) -> CrawlResponse | None:
        _logger.debug(
            "Hook: response %s status=%d cached=%s",
            response.url,
            response.status_code,
            response.from_cache,
        )
        return response


class AuthHeaderHook(BaseHook):
    """Injects custom headers into requests via request.metadata["headers"].

    Usage:
        hook = AuthHeaderHook({"Authorization": "Bearer token123"})
    """

    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    async def on_request(self, request: CrawlRequest) -> CrawlRequest | None:
        existing = request.metadata.get("headers", {})
        merged = {**existing, **self._headers}
        request.metadata["headers"] = merged
        return request


class StatusFilterHook(BaseHook):
    """Discards responses that don't match allowed status codes.

    By default, only keeps 200 responses. Pass a custom set to override.
    """

    def __init__(self, allowed: set[int] | None = None) -> None:
        self._allowed = allowed or {200}

    async def on_response(self, response: CrawlResponse) -> CrawlResponse | None:
        if response.status_code in self._allowed:
            return response
        _logger.debug(
            "StatusFilterHook: discarding %s (status=%d)",
            response.url,
            response.status_code,
        )
        return None
