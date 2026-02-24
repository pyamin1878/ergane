"""Authentication manager — orchestrates login and session lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ergane.auth.config import AuthConfig
from ergane.auth.errors import AuthenticationError
from ergane.auth.session_store import SessionStore

_logger = logging.getLogger(__name__)


class AuthManager:
    """Orchestrates login flow and cookie injection into httpx.

    If config is None, all operations are no-ops (unauthenticated crawl).
    """

    def __init__(
        self,
        config: AuthConfig | None,
        session_dir: Path | None = None,
    ) -> None:
        self._config = config
        if config is not None:
            session_path = Path(session_dir or ".") / config.session_file
            self._store = SessionStore(session_path)
        else:
            self._store = None

    @property
    def is_noop(self) -> bool:
        return self._config is None

    async def ensure_authenticated(self, client: httpx.AsyncClient) -> None:
        """Ensure the httpx client has valid session cookies.

        1. Try loading saved session and validating it.
        2. If invalid/missing, run the login flow via Playwright.
        3. Inject cookies into the client.
        """
        if self.is_noop:
            return

        config = self._config
        assert config is not None

        # Try saved session first
        saved = self._store.load(max_age=config.session_ttl)
        if saved:
            self._inject_cookies(client, saved)
            if await self._validate_session(client):
                _logger.info("Reusing saved session")
                return
            _logger.info("Saved session is stale, re-authenticating")

        # Need fresh login via Playwright
        cookies = await self._playwright_login(config)
        self._store.save(cookies)
        self._inject_cookies(client, cookies)

        if config.check_url and not await self._validate_session(client):
            raise AuthenticationError(
                "Login appeared to succeed but session validation failed"
            )
        _logger.info("Authentication successful")

    async def _validate_session(self, client: httpx.AsyncClient) -> bool:
        """GET the check_url with current cookies. 2xx = valid."""
        if not self._config or not self._config.check_url:
            return True
        try:
            resp = await client.get(self._config.check_url)
            return 200 <= resp.status_code < 300
        except httpx.HTTPError:
            return False

    async def _playwright_login(self, config: AuthConfig) -> list[dict]:
        """Run the login flow in Playwright and return cookies."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AuthenticationError(
                "Auth requires playwright. Install with: uv pip install ergane[js]"
            ) from exc

        async with async_playwright() as p:
            headless = config.mode == "auto"
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(config.login_url)

                if config.mode == "auto":
                    await self._auto_login(page, config)
                else:
                    await self._manual_login(page)

                # Wait for post-login navigation
                if config.wait_after_login:
                    wc = config.wait_after_login
                    if wc in ("networkidle", "domcontentloaded", "load"):
                        await page.wait_for_load_state(wc)
                    else:
                        await page.wait_for_selector(wc)

                cookies = await context.cookies()
                return [
                    {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c["domain"],
                        "path": c["path"],
                    }
                    for c in cookies
                ]
            finally:
                await browser.close()

    async def _auto_login(self, page, config: AuthConfig) -> None:
        """Fill login form and submit."""
        if config.username_selector and config.username:
            el = page.locator(config.username_selector)
            if await el.count() == 0:
                raise AuthenticationError(
                    f"Selector not found: {config.username_selector}"
                )
            await el.fill(config.username)

        if config.password_selector and config.password:
            el = page.locator(config.password_selector)
            if await el.count() == 0:
                raise AuthenticationError(
                    f"Selector not found: {config.password_selector}"
                )
            await el.fill(config.password)

        if config.submit_selector:
            el = page.locator(config.submit_selector)
            if await el.count() == 0:
                raise AuthenticationError(
                    f"Selector not found: {config.submit_selector}"
                )
            await el.click()
        else:
            await page.keyboard.press("Enter")

    async def _manual_login(self, page) -> None:
        """Wait for user to complete login interactively."""
        import sys

        print(  # noqa: T201
            "\n  Browser opened. Log in manually, then press Enter here to continue...",
            file=sys.stderr,
        )
        await _async_input()

    @staticmethod
    def _inject_cookies(
        client: httpx.AsyncClient, cookies: list[dict]
    ) -> None:
        """Set cookies on the httpx client."""
        for c in cookies:
            client.cookies.set(c["name"], c["value"], domain=c.get("domain"))


async def _async_input() -> str:
    """Non-blocking input() that doesn't freeze the event loop."""
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, input)
