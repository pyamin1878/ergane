"""Tests for ergane.auth.manager.AuthManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ergane.auth.config import AuthConfig
from ergane.auth.errors import AuthenticationError
from ergane.auth.manager import AuthManager


@pytest.fixture()
def auto_config():
    return AuthConfig(
        login_url="https://example.com/login",
        mode="auto",
        username_selector="#email",
        password_selector="#pass",
        submit_selector="button[type='submit']",
        username="alice",
        password="secret",
        check_url="https://example.com/dashboard",
        session_file=".test_session.json",
        session_ttl=3600,
    )


@pytest.fixture()
def manual_config():
    return AuthConfig(
        login_url="https://example.com/login",
        mode="manual",
        check_url="https://example.com/dashboard",
    )


@pytest.fixture()
def manager(auto_config, tmp_path):
    return AuthManager(auto_config, session_dir=tmp_path)


class TestAuthManagerInit:
    def test_creates_from_config(self, auto_config, tmp_path):
        mgr = AuthManager(auto_config, session_dir=tmp_path)
        assert mgr._config is auto_config

    def test_none_config_returns_noop(self):
        mgr = AuthManager(None)
        assert mgr.is_noop


class TestEnsureAuthenticated:
    async def test_noop_when_no_config(self):
        mgr = AuthManager(None)
        client = httpx.AsyncClient()
        try:
            await mgr.ensure_authenticated(client)
            # Should not raise, should not modify client
        finally:
            await client.aclose()

    async def test_reuses_valid_session(self, auto_config, tmp_path):
        mgr = AuthManager(auto_config, session_dir=tmp_path)
        # Pre-populate session store with valid cookies
        mgr._store.save([
            {"name": "session_id", "value": "valid", "domain": "example.com", "path": "/"},
        ])
        client = httpx.AsyncClient()
        try:
            # Mock the validation request
            with patch.object(mgr, "_validate_session", return_value=True):
                await mgr.ensure_authenticated(client)
                assert client.cookies.get("session_id") == "valid"
        finally:
            await client.aclose()

    async def test_raises_when_playwright_missing(self, auto_config, tmp_path):
        mgr = AuthManager(auto_config, session_dir=tmp_path)
        client = httpx.AsyncClient()
        try:
            with patch.object(mgr, "_validate_session", return_value=False):
                with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
                    with pytest.raises(AuthenticationError, match="playwright"):
                        await mgr.ensure_authenticated(client)
        finally:
            await client.aclose()


class TestValidateSession:
    async def test_valid_check_url(self, auto_config, tmp_path):
        mgr = AuthManager(auto_config, session_dir=tmp_path)
        mock_response = MagicMock()
        mock_response.status_code = 200
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_response)
        assert await mgr._validate_session(client) is True

    async def test_invalid_check_url(self, auto_config, tmp_path):
        mgr = AuthManager(auto_config, session_dir=tmp_path)
        mock_response = MagicMock()
        mock_response.status_code = 403
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_response)
        assert await mgr._validate_session(client) is False

    async def test_no_check_url_always_valid(self, tmp_path):
        cfg = AuthConfig(
            login_url="https://example.com/login",
            mode="manual",
        )
        mgr = AuthManager(cfg, session_dir=tmp_path)
        client = AsyncMock(spec=httpx.AsyncClient)
        assert await mgr._validate_session(client) is True
