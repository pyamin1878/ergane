"""Integration test: full auth round-trip with mocked Playwright."""

from unittest.mock import AsyncMock, patch

import httpx

from ergane.auth.config import AuthConfig
from ergane.auth.manager import AuthManager

FRESH_COOKIES = [
    {
        "name": "session_id", "value": "fresh123",
        "domain": "example.com", "path": "/",
    },
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


def _cookie(name, value):
    return {
        "name": name, "value": value,
        "domain": "example.com", "path": "/",
    }


class TestAuthRoundTrip:
    async def test_fresh_login_injects_cookies(self, tmp_path):
        cfg = _make_auto_config()
        mgr = AuthManager(cfg, session_dir=tmp_path)

        async with httpx.AsyncClient() as client:
            with patch.object(
                mgr, "_playwright_login",
                new_callable=AsyncMock,
                return_value=FRESH_COOKIES,
            ):
                with patch.object(
                    mgr, "_validate_session",
                    return_value=True,
                ):
                    await mgr.ensure_authenticated(client)

            assert client.cookies.get("session_id") == "fresh123"

    async def test_saved_session_reused(self, tmp_path):
        cfg = _make_auto_config()
        mgr = AuthManager(cfg, session_dir=tmp_path)
        mgr._store.save([_cookie("session_id", "saved456")])

        async with httpx.AsyncClient() as client:
            with patch.object(
                mgr, "_validate_session", return_value=True,
            ):
                await mgr.ensure_authenticated(client)

            assert client.cookies.get("session_id") == "saved456"

    async def test_stale_session_triggers_relogin(self, tmp_path):
        cfg = _make_auto_config()
        mgr = AuthManager(cfg, session_dir=tmp_path)
        mgr._store.save([_cookie("session_id", "old789")])

        call_count = 0

        async def validate_side_effect(client):
            nonlocal call_count
            call_count += 1
            return call_count > 1

        async with httpx.AsyncClient() as client:
            with patch.object(
                mgr, "_validate_session",
                side_effect=validate_side_effect,
            ):
                with patch.object(
                    mgr, "_playwright_login",
                    new_callable=AsyncMock,
                    return_value=FRESH_COOKIES,
                ):
                    await mgr.ensure_authenticated(client)

            assert client.cookies.get("session_id") == "fresh123"
