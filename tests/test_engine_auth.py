"""Tests for auth integration in Crawler engine."""

from unittest.mock import AsyncMock, patch

from ergane.auth.config import AuthConfig
from ergane.auth.manager import AuthManager
from ergane.crawler.engine import Crawler


class TestCrawlerAuth:
    async def test_crawler_accepts_auth_config(self):
        auth_cfg = AuthConfig(
            login_url="https://example.com/login",
            mode="manual",
        )
        crawler = Crawler(
            urls=["https://example.com"],
            auth=auth_cfg,
        )
        assert crawler._auth_manager is not None
        assert not crawler._auth_manager.is_noop

    async def test_crawler_no_auth_by_default(self):
        crawler = Crawler(urls=["https://example.com"])
        assert crawler._auth_manager.is_noop

    async def test_aenter_calls_ensure_authenticated(self):
        auth_cfg = AuthConfig(
            login_url="https://example.com/login",
            mode="manual",
        )
        crawler = Crawler(
            urls=["https://example.com"],
            auth=auth_cfg,
        )
        with patch.object(
            AuthManager, "ensure_authenticated", new_callable=AsyncMock
        ) as mock_auth:
            async with crawler:
                mock_auth.assert_called_once()
