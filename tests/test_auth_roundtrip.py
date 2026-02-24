"""Integration test: full auth round-trip with mocked Playwright."""

from unittest.mock import AsyncMock, patch

import httpx

from ergane.auth.config import AuthConfig
from ergane.auth.manager import AuthManager


FRESH_COOKIES = [
    {"name": "session_id", "value": "fresh123", "domain": "example.com", "path": "/"},
]


def _make_auto_config():
    return AuthConfig(
        login_url="https://example.com/login",
        mode="auto",
        username_selector="#email",
        password_selector="#pass",
        submit_selector="button[type='submit']",
        username="alice",
        password="secret",
        check_url="https://example.com/dashboard",
        session_ttl=3600,
    )


class TestAuthRoundTrip:
    async def test_fresh_login_injects_cookies(self, tmp_path):
        auth_config = _make_auto_config()
        mgr = AuthManager(auth_config, session_dir=tmp_path)

        async with httpx.AsyncClient() as client:
            # Mock _playwright_login to return fresh cookies (avoids needing real Playwright)
            with patch.object(
                mgr, "_playwright_login", new_callable=AsyncMock, return_value=FRESH_COOKIES
            ):
                with patch.object(mgr, "_validate_session", return_value=True):
                    await mgr.ensure_authenticated(client)

            assert client.cookies.get("session_id") == "fresh123"

    async def test_saved_session_reused(self, tmp_path):
        auth_config = _make_auto_config()
        mgr = AuthManager(auth_config, session_dir=tmp_path)
        # Pre-save a session
        mgr._store.save([
            {"name": "session_id", "value": "saved456", "domain": "example.com", "path": "/"},
        ])

        async with httpx.AsyncClient() as client:
            with patch.object(mgr, "_validate_session", return_value=True):
                await mgr.ensure_authenticated(client)

            assert client.cookies.get("session_id") == "saved456"

    async def test_stale_session_triggers_relogin(self, tmp_path):
        auth_config = _make_auto_config()
        mgr = AuthManager(auth_config, session_dir=tmp_path)
        # Pre-save an old session
        mgr._store.save([
            {"name": "session_id", "value": "old789", "domain": "example.com", "path": "/"},
        ])

        call_count = 0

        async def validate_side_effect(client):
            nonlocal call_count
            call_count += 1
            # First call (old cookies) fails, second call (new cookies) succeeds
            return call_count > 1

        async with httpx.AsyncClient() as client:
            with patch.object(mgr, "_validate_session", side_effect=validate_side_effect):
                with patch.object(
                    mgr, "_playwright_login", new_callable=AsyncMock, return_value=FRESH_COOKIES
                ):
                    await mgr.ensure_authenticated(client)

            # Should have the fresh cookies from re-login
            assert client.cookies.get("session_id") == "fresh123"
