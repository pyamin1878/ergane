"""Tests for the hook system."""

import pytest

from ergane.crawler.hooks import (
    AuthHeaderHook,
    BaseHook,
    CrawlHook,
    LoggingHook,
    StatusFilterHook,
)
from ergane.models import CrawlRequest, CrawlResponse


@pytest.fixture
def request_obj() -> CrawlRequest:
    return CrawlRequest(url="https://example.com/page", depth=1, priority=0)


@pytest.fixture
def response_obj(request_obj: CrawlRequest) -> CrawlResponse:
    return CrawlResponse(
        url="https://example.com/page",
        status_code=200,
        content="<html></html>",
        headers={"content-type": "text/html"},
        request=request_obj,
    )


class TestCrawlHookProtocol:
    """Protocol conformance tests."""

    def test_base_hook_satisfies_protocol(self):
        hook = BaseHook()
        assert isinstance(hook, CrawlHook)

    def test_logging_hook_satisfies_protocol(self):
        hook = LoggingHook()
        assert isinstance(hook, CrawlHook)

    def test_auth_header_hook_satisfies_protocol(self):
        hook = AuthHeaderHook({"Authorization": "Bearer x"})
        assert isinstance(hook, CrawlHook)

    def test_status_filter_hook_satisfies_protocol(self):
        hook = StatusFilterHook()
        assert isinstance(hook, CrawlHook)

    def test_custom_class_satisfies_protocol(self):
        class MyHook:
            async def on_request(self, request):
                return request

            async def on_response(self, response):
                return response

        assert isinstance(MyHook(), CrawlHook)


class TestBaseHook:
    """BaseHook passthrough tests."""

    @pytest.mark.asyncio
    async def test_on_request_passthrough(self, request_obj):
        hook = BaseHook()
        result = await hook.on_request(request_obj)
        assert result is request_obj

    @pytest.mark.asyncio
    async def test_on_response_passthrough(self, response_obj):
        hook = BaseHook()
        result = await hook.on_response(response_obj)
        assert result is response_obj


class TestLoggingHook:
    """LoggingHook tests."""

    @pytest.mark.asyncio
    async def test_on_request_returns_request(self, request_obj):
        hook = LoggingHook()
        result = await hook.on_request(request_obj)
        assert result is request_obj

    @pytest.mark.asyncio
    async def test_on_response_returns_response(self, response_obj):
        hook = LoggingHook()
        result = await hook.on_response(response_obj)
        assert result is response_obj


class TestAuthHeaderHook:
    """AuthHeaderHook tests."""

    @pytest.mark.asyncio
    async def test_injects_headers(self, request_obj):
        hook = AuthHeaderHook({"Authorization": "Bearer token123"})
        result = await hook.on_request(request_obj)
        assert result is not None
        assert result.metadata["headers"]["Authorization"] == "Bearer token123"

    @pytest.mark.asyncio
    async def test_merges_with_existing_headers(self, request_obj):
        request_obj.metadata["headers"] = {"X-Custom": "existing"}
        hook = AuthHeaderHook({"Authorization": "Bearer token123"})
        result = await hook.on_request(request_obj)
        assert result is not None
        assert result.metadata["headers"]["X-Custom"] == "existing"
        assert result.metadata["headers"]["Authorization"] == "Bearer token123"

    @pytest.mark.asyncio
    async def test_on_response_passthrough(self, response_obj):
        hook = AuthHeaderHook({"Authorization": "Bearer token123"})
        result = await hook.on_response(response_obj)
        assert result is response_obj


class TestStatusFilterHook:
    """StatusFilterHook tests."""

    @pytest.mark.asyncio
    async def test_allows_200(self, response_obj):
        hook = StatusFilterHook()
        result = await hook.on_response(response_obj)
        assert result is response_obj

    @pytest.mark.asyncio
    async def test_discards_non_200(self, response_obj):
        response_obj.status_code = 404
        hook = StatusFilterHook()
        result = await hook.on_response(response_obj)
        assert result is None

    @pytest.mark.asyncio
    async def test_custom_allowed_statuses(self, response_obj):
        response_obj.status_code = 301
        hook = StatusFilterHook(allowed={200, 301, 302})
        result = await hook.on_response(response_obj)
        assert result is response_obj

    @pytest.mark.asyncio
    async def test_on_request_passthrough(self, request_obj):
        hook = StatusFilterHook()
        result = await hook.on_request(request_obj)
        assert result is request_obj
