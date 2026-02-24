# Auth & Session Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Playwright-based authentication with automated and manual login modes, encrypted session persistence, and cookie injection into httpx for crawling.

**Architecture:** All login flows run through a Playwright browser. After login, cookies are extracted and injected into the httpx `AsyncClient` that powers the actual crawl. Sessions persist to an encrypted JSON file with a staleness check on reload. Three new modules under `ergane/auth/`: `AuthConfig` (Pydantic model), `SessionStore` (encrypted persistence), `AuthManager` (orchestrator).

**Tech Stack:** Playwright (already optional via `[js]`), `cryptography` (Fernet encryption, new core dep), httpx cookie injection, Pydantic config models.

**Depends on:** The Playwright/JS-rendering feature branch must be merged first, since auth uses `playwright` from the `[js]` extra.

---

### Task 1: AuthConfig Pydantic Model

**Files:**
- Create: `ergane/auth/__init__.py`
- Create: `ergane/auth/config.py`
- Test: `tests/test_auth_config.py`

**Step 1: Write the failing tests**

Create `tests/test_auth_config.py`:

```python
"""Tests for ergane.auth.config.AuthConfig."""

import os

import pytest
from pydantic import ValidationError

from ergane.auth.config import AuthConfig


class TestAuthConfig:
    def test_minimal_config(self):
        cfg = AuthConfig(login_url="https://example.com/login")
        assert cfg.login_url == "https://example.com/login"
        assert cfg.mode == "auto"
        assert cfg.session_ttl == 3600

    def test_full_config(self):
        cfg = AuthConfig(
            login_url="https://example.com/login",
            mode="manual",
            username_selector="#email",
            password_selector="#pass",
            submit_selector="button[type='submit']",
            username="alice",
            password="secret",
            check_url="https://example.com/dashboard",
            session_file=".my_session.json",
            session_ttl=7200,
            wait_after_login="networkidle",
        )
        assert cfg.mode == "manual"
        assert cfg.session_ttl == 7200

    def test_mode_validation(self):
        with pytest.raises(ValidationError, match="mode"):
            AuthConfig(login_url="https://example.com/login", mode="invalid")

    def test_login_url_required(self):
        with pytest.raises(ValidationError, match="login_url"):
            AuthConfig()

    def test_env_var_interpolation(self, monkeypatch):
        monkeypatch.setenv("TEST_USER", "alice")
        monkeypatch.setenv("TEST_PASS", "secret123")
        cfg = AuthConfig(
            login_url="https://example.com/login",
            username="${TEST_USER}",
            password="${TEST_PASS}",
        )
        assert cfg.username == "alice"
        assert cfg.password == "secret123"

    def test_env_var_missing_left_as_is(self):
        cfg = AuthConfig(
            login_url="https://example.com/login",
            username="${NONEXISTENT_VAR_XYZ}",
        )
        assert cfg.username == "${NONEXISTENT_VAR_XYZ}"

    def test_auto_mode_requires_selectors(self):
        """Auto mode without selectors should raise."""
        with pytest.raises(ValidationError, match="username_selector"):
            AuthConfig(
                login_url="https://example.com/login",
                mode="auto",
                username="alice",
                password="secret",
                # Missing selectors
            )

    def test_manual_mode_no_selectors_ok(self):
        cfg = AuthConfig(
            login_url="https://example.com/login",
            mode="manual",
        )
        assert cfg.mode == "manual"
        assert cfg.username_selector is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ergane.auth'`

**Step 3: Write minimal implementation**

Create `ergane/auth/__init__.py`:

```python
from ergane.auth.config import AuthConfig

__all__ = ["AuthConfig"]
```

Create `ergane/auth/config.py`:

```python
"""Authentication configuration model."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _interpolate_env(value: str | None) -> str | None:
    """Replace ${VAR} with environment variable values. Leave as-is if unset."""
    if value is None:
        return None
    return re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.environ.get(m.group(1), m.group(0)),
        value,
    )


class AuthConfig(BaseModel):
    """Configuration for the auth section of ergane.yaml."""

    login_url: str
    mode: Literal["auto", "manual"] = "auto"

    # CSS selectors for automated login (mode: auto)
    username_selector: str | None = None
    password_selector: str | None = None
    submit_selector: str | None = Field(
        default=None,
        description="CSS selector for the login submit button",
    )

    # Credentials (support ${ENV_VAR} interpolation)
    username: str | None = None
    password: str | None = None

    # Session validation
    check_url: str | None = None
    session_file: str = ".ergane_session.json"
    session_ttl: int = Field(default=3600, gt=0)

    # Wait condition after login
    wait_after_login: str | None = Field(
        default=None,
        description="Playwright wait: 'networkidle', 'domcontentloaded', 'load', or a CSS selector",
    )

    @model_validator(mode="after")
    def _validate_auto_mode(self) -> AuthConfig:
        if self.mode == "auto":
            if self.username is not None and self.username_selector is None:
                raise ValueError(
                    "mode='auto' with credentials requires username_selector"
                )
            if self.password is not None and self.password_selector is None:
                raise ValueError(
                    "mode='auto' with credentials requires password_selector"
                )
        return self

    @model_validator(mode="after")
    def _interpolate_credentials(self) -> AuthConfig:
        self.username = _interpolate_env(self.username)
        self.password = _interpolate_env(self.password)
        return self
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_config.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add ergane/auth/__init__.py ergane/auth/config.py tests/test_auth_config.py
git commit -m "feat(auth): add AuthConfig pydantic model with env var interpolation"
```

---

### Task 2: SessionStore — Encrypted Cookie Persistence

**Files:**
- Create: `ergane/auth/session_store.py`
- Modify: `ergane/auth/__init__.py`
- Test: `tests/test_session_store.py`

**Step 1: Write the failing tests**

Create `tests/test_session_store.py`:

```python
"""Tests for ergane.auth.session_store.SessionStore."""

import json
import time

import pytest

from ergane.auth.session_store import SessionStore


@pytest.fixture()
def store(tmp_path):
    return SessionStore(session_file=tmp_path / "session.json", passphrase="test-key")


@pytest.fixture()
def sample_cookies():
    return [
        {"name": "session_id", "value": "abc123", "domain": "example.com", "path": "/"},
        {"name": "csrf", "value": "xyz789", "domain": "example.com", "path": "/"},
    ]


class TestSessionStore:
    def test_save_and_load(self, store, sample_cookies):
        store.save(sample_cookies)
        loaded = store.load()
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["name"] == "session_id"

    def test_load_nonexistent(self, store):
        assert store.load() is None

    def test_load_expired(self, store, sample_cookies):
        store.save(sample_cookies)
        # Manually backdate the saved_at timestamp
        raw = store._session_file.read_bytes()
        from cryptography.fernet import Fernet
        import base64
        import hashlib
        key = base64.urlsafe_b64encode(hashlib.sha256(b"test-key").digest())
        f = Fernet(key)
        data = json.loads(f.decrypt(raw))
        data["saved_at"] = time.time() - 99999
        store._session_file.write_bytes(f.encrypt(json.dumps(data).encode()))

        loaded = store.load(max_age=3600)
        assert loaded is None

    def test_load_within_ttl(self, store, sample_cookies):
        store.save(sample_cookies)
        loaded = store.load(max_age=3600)
        assert loaded is not None

    def test_encrypted_on_disk(self, store, sample_cookies):
        store.save(sample_cookies)
        raw = store._session_file.read_bytes()
        # Should not contain plaintext cookie values
        assert b"abc123" not in raw

    def test_wrong_passphrase(self, store, sample_cookies, tmp_path):
        store.save(sample_cookies)
        wrong = SessionStore(session_file=tmp_path / "session.json", passphrase="wrong")
        assert wrong.load() is None

    def test_clear(self, store, sample_cookies):
        store.save(sample_cookies)
        assert store._session_file.exists()
        store.clear()
        assert not store._session_file.exists()

    def test_clear_nonexistent(self, store):
        # Should not raise
        store.clear()

    def test_fallback_machine_key(self, tmp_path):
        """SessionStore with no passphrase uses a machine-local fallback."""
        store = SessionStore(session_file=tmp_path / "session.json")
        cookies = [{"name": "x", "value": "y", "domain": "d", "path": "/"}]
        store.save(cookies)
        assert store.load() is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ergane.auth.session_store'`

**Step 3: Add cryptography dependency**

In `pyproject.toml`, add `"cryptography>=41.0.0"` to the `dependencies` list.

**Step 4: Write minimal implementation**

Create `ergane/auth/session_store.py`:

```python
"""Encrypted session cookie persistence."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_logger = logging.getLogger(__name__)

# Machine-local fallback key file (created once, reused)
_MACHINE_KEY_PATH = Path.home() / ".ergane" / ".machine_key"


def _derive_key(passphrase: str) -> bytes:
    """Derive a Fernet key from a passphrase via SHA-256."""
    return base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode()).digest())


def _machine_key() -> str:
    """Return a stable machine-local passphrase, creating one if needed."""
    _MACHINE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _MACHINE_KEY_PATH.exists():
        return _MACHINE_KEY_PATH.read_text().strip()
    key = uuid.uuid4().hex
    _MACHINE_KEY_PATH.write_text(key)
    _MACHINE_KEY_PATH.chmod(0o600)
    return key


class SessionStore:
    """Save and load encrypted session cookies to disk."""

    def __init__(
        self,
        session_file: str | Path,
        passphrase: str | None = None,
    ) -> None:
        self._session_file = Path(session_file)
        key_material = passphrase or _machine_key()
        self._fernet = Fernet(_derive_key(key_material))

    def save(self, cookies: list[dict]) -> None:
        """Encrypt and write cookies to disk."""
        payload = json.dumps({"saved_at": time.time(), "cookies": cookies})
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_file.write_bytes(self._fernet.encrypt(payload.encode()))

    def load(self, max_age: int | None = None) -> list[dict] | None:
        """Load cookies from disk. Returns None if missing, expired, or corrupt."""
        if not self._session_file.exists():
            return None
        try:
            raw = self._fernet.decrypt(self._session_file.read_bytes())
            data = json.loads(raw)
        except (InvalidToken, json.JSONDecodeError):
            _logger.warning("Session file corrupt or wrong passphrase; ignoring")
            return None
        if max_age is not None:
            age = time.time() - data.get("saved_at", 0)
            if age > max_age:
                _logger.info("Session expired (age=%.0fs, max=%ds)", age, max_age)
                return None
        return data.get("cookies")

    def clear(self) -> None:
        """Delete the session file."""
        if self._session_file.exists():
            self._session_file.unlink()
```

Update `ergane/auth/__init__.py`:

```python
from ergane.auth.config import AuthConfig
from ergane.auth.session_store import SessionStore

__all__ = ["AuthConfig", "SessionStore"]
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_session_store.py -v`
Expected: All 10 tests PASS

**Step 6: Commit**

```bash
git add pyproject.toml ergane/auth/session_store.py ergane/auth/__init__.py tests/test_session_store.py
git commit -m "feat(auth): add SessionStore with Fernet-encrypted cookie persistence"
```

---

### Task 3: AuthenticationError Exception

**Files:**
- Create: `ergane/auth/errors.py`
- Modify: `ergane/auth/__init__.py`
- Test: `tests/test_auth_config.py` (add to existing)

**Step 1: Write the failing test**

Append to `tests/test_auth_config.py`:

```python
from ergane.auth.errors import AuthenticationError


class TestAuthenticationError:
    def test_is_exception(self):
        err = AuthenticationError("Login failed")
        assert isinstance(err, Exception)
        assert str(err) == "Login failed"

    def test_with_cause(self):
        cause = TimeoutError("connection timed out")
        err = AuthenticationError("Login failed", cause=cause)
        assert err.__cause__ is cause
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_config.py::TestAuthenticationError -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `ergane/auth/errors.py`:

```python
"""Authentication error types."""


class AuthenticationError(Exception):
    """Raised when authentication fails before crawling starts."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause
```

Update `ergane/auth/__init__.py` to add:

```python
from ergane.auth.config import AuthConfig
from ergane.auth.errors import AuthenticationError
from ergane.auth.session_store import SessionStore

__all__ = ["AuthConfig", "AuthenticationError", "SessionStore"]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_config.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add ergane/auth/errors.py ergane/auth/__init__.py tests/test_auth_config.py
git commit -m "feat(auth): add AuthenticationError exception"
```

---

### Task 4: AuthManager — Core Orchestrator

**Files:**
- Create: `ergane/auth/manager.py`
- Modify: `ergane/auth/__init__.py`
- Test: `tests/test_auth_manager.py`

This is the largest task. AuthManager coordinates SessionStore and Playwright for login.

**Step 1: Write the failing tests**

Create `tests/test_auth_manager.py`:

```python
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
                with patch.dict("sys.modules", {"playwright.async_api": None}):
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ergane.auth.manager'`

**Step 3: Write minimal implementation**

Create `ergane/auth/manager.py`:

```python
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
        except ImportError:
            raise AuthenticationError(
                "Auth requires playwright. Install with: uv pip install ergane[js]"
            )

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
```

Update `ergane/auth/__init__.py`:

```python
from ergane.auth.config import AuthConfig
from ergane.auth.errors import AuthenticationError
from ergane.auth.manager import AuthManager
from ergane.auth.session_store import SessionStore

__all__ = ["AuthConfig", "AuthenticationError", "AuthManager", "SessionStore"]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_manager.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add ergane/auth/manager.py ergane/auth/__init__.py tests/test_auth_manager.py
git commit -m "feat(auth): add AuthManager with Playwright login and session reuse"
```

---

### Task 5: Wire Auth into CrawlOptions and CrawlConfig

**Files:**
- Modify: `ergane/config.py:17-30` (add `"auth"` to valid sections)
- Modify: `ergane/config.py:100-242` (add auth fields to `CrawlOptions`)
- Modify: `ergane/models/schemas.py:15-35` (add auth config to `CrawlConfig`)
- Test: `tests/test_config.py` (add auth config tests — find existing test file)

**Step 1: Write the failing test**

Find the existing config test file and append auth-specific tests. If `tests/test_config.py` exists, append there. Otherwise create `tests/test_auth_integration.py`:

```python
"""Tests for auth wiring into CrawlOptions and CrawlConfig."""

import pytest

from ergane.config import CrawlOptions


class TestCrawlOptionsAuth:
    def test_default_no_auth(self):
        opts = CrawlOptions()
        assert opts.auth is None

    def test_from_sources_with_auth_section(self):
        file_config = {
            "auth": {
                "login_url": "https://example.com/login",
                "mode": "auto",
                "username_selector": "#user",
                "password_selector": "#pass",
                "username": "alice",
                "password": "secret",
            },
            "crawler": {},
        }
        opts = CrawlOptions.from_sources(file_config)
        assert opts.auth is not None
        assert opts.auth.login_url == "https://example.com/login"
        assert opts.auth.mode == "auto"

    def test_from_sources_without_auth(self):
        opts = CrawlOptions.from_sources({})
        assert opts.auth is None

    def test_cli_auth_mode_override(self):
        file_config = {
            "auth": {
                "login_url": "https://example.com/login",
                "mode": "auto",
                "username_selector": "#user",
                "password_selector": "#pass",
                "username": "alice",
                "password": "secret",
            },
        }
        opts = CrawlOptions.from_sources(file_config, auth_mode="manual")
        assert opts.auth is not None
        assert opts.auth.mode == "manual"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_integration.py -v` (or the appropriate file)
Expected: FAIL — `opts.auth` attribute doesn't exist

**Step 3: Write minimal implementation**

Modify `ergane/config.py`:

1. Add `"auth"` to `_VALID_SECTIONS` (line 17).
2. Add `_VALID_SECTION_KEYS["auth"]` with known auth keys.
3. Add `auth: AuthConfig | None = None` field to `CrawlOptions` dataclass (after line 135).
4. In `from_sources()`, parse the `"auth"` section from `file_config` and build an `AuthConfig`.
5. Add `auth_mode: str | None = None` CLI override parameter.

Key changes to `ergane/config.py`:

```python
# At top, add import:
from ergane.auth.config import AuthConfig

# Line 17: add "auth" to valid sections
_VALID_SECTIONS = {"crawler", "defaults", "logging", "auth"}

# After line 31, add:
"auth": {
    "login_url", "mode", "username_selector", "password_selector",
    "submit_selector", "username", "password", "check_url",
    "session_file", "session_ttl", "wait_after_login",
},

# In CrawlOptions dataclass, after log_file (line 135):
auth: AuthConfig | None = None

# In from_sources() parameter list, add:
auth_mode: str | None = None,

# In from_sources() body, after the existing file-config processing (line 206):
auth_raw = file_config.get("auth")
if auth_raw:
    if auth_mode is not None:
        auth_raw["mode"] = auth_mode
    opts.auth = AuthConfig(**auth_raw)
elif auth_mode is not None:
    # CLI auth_mode without file config — can't construct AuthConfig without login_url
    pass
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_integration.py -v`
Expected: All 4 tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All existing tests still pass (auth is None by default, no behavioral change)

**Step 6: Commit**

```bash
git add ergane/config.py tests/test_auth_integration.py
git commit -m "feat(auth): wire AuthConfig into CrawlOptions config pipeline"
```

---

### Task 6: Wire AuthManager into Engine

**Files:**
- Modify: `ergane/crawler/engine.py:53-95` (add auth parameter to `Crawler.__init__`)
- Modify: `ergane/crawler/engine.py:165-169` (call auth in `__aenter__`)
- Test: `tests/test_engine.py` (add auth integration tests)

**Step 1: Write the failing test**

Add to `tests/test_engine.py` (or create `tests/test_engine_auth.py`):

```python
"""Tests for auth integration in Crawler engine."""

from unittest.mock import AsyncMock, patch

import pytest

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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine_auth.py -v`
Expected: FAIL — `Crawler() got an unexpected keyword argument 'auth'`

**Step 3: Write minimal implementation**

Modify `ergane/crawler/engine.py`:

1. Add import at top: `from ergane.auth.manager import AuthManager`
2. Add `auth: AuthConfig | None = None` parameter to `Crawler.__init__()` (after `config` param, line 76).
3. In `__init__` body, create `self._auth_manager = AuthManager(auth)`.
4. In `__aenter__()`, after creating the Fetcher and before returning, call `await self._auth_manager.ensure_authenticated(self._fetcher._client)`.

Key changes:

```python
# In __init__ parameter list (after line 76):
auth: AuthConfig | None = None,

# In __init__ body (after line 95):
self._auth_manager = AuthManager(auth)

# In __aenter__ (lines 165-169), add auth call:
async def __aenter__(self) -> Crawler:
    self._fetcher = Fetcher(self._config)
    await self._fetcher.__aenter__()
    self._owns_fetcher = True
    await self._auth_manager.ensure_authenticated(self._fetcher._client)
    return self
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine_auth.py -v`
Expected: All 3 tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass (default `auth=None` means no behavioral change)

**Step 6: Commit**

```bash
git add ergane/crawler/engine.py tests/test_engine_auth.py
git commit -m "feat(auth): wire AuthManager into Crawler engine lifecycle"
```

---

### Task 7: CLI Integration — `--auth-mode` Flag and `ergane auth` Subcommands

**Files:**
- Modify: `ergane/main.py:103-243` (add `--auth-mode` to crawl command)
- Modify: `ergane/main.py:515-521` (add `auth` command group after `mcp`)
- Modify: `ergane/main.py:370-391` (pass auth to Crawler)
- Test: `tests/test_cli_auth.py`

**Step 1: Write the failing tests**

Create `tests/test_cli_auth.py`:

```python
"""Tests for auth CLI commands."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ergane.main import cli


@pytest.fixture()
def runner():
    return CliRunner()


class TestAuthCommands:
    def test_auth_status_no_session(self, runner, tmp_path):
        result = runner.invoke(cli, ["auth", "status", "--session-file", str(tmp_path / "none.json")])
        assert result.exit_code == 0
        assert "No saved session" in result.output

    def test_auth_clear_no_session(self, runner, tmp_path):
        result = runner.invoke(cli, ["auth", "clear", "--session-file", str(tmp_path / "none.json")])
        assert result.exit_code == 0

    def test_auth_help(self, runner):
        result = runner.invoke(cli, ["auth", "--help"])
        assert result.exit_code == 0
        assert "login" in result.output
        assert "status" in result.output
        assert "clear" in result.output


class TestCrawlAuthMode:
    def test_auth_mode_flag_accepted(self, runner):
        """Verify --auth-mode is a recognized option (doesn't error on parse)."""
        result = runner.invoke(cli, ["crawl", "--auth-mode", "manual", "--help"])
        # --help exits 0; we're just checking the flag is recognized
        assert result.exit_code == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_auth.py -v`
Expected: FAIL — `"auth"` command not found / `--auth-mode` not recognized

**Step 3: Write minimal implementation**

Modify `ergane/main.py`:

1. Add `--auth-mode` option to the `crawl` command (around line 218, after `--cache-ttl`):

```python
@click.option(
    "--auth-mode",
    type=click.Choice(["auto", "manual"]),
    default=None,
    help="Override auth mode from config (auto=headless, manual=visible browser).",
)
```

2. Add `auth_mode: str | None` to the `crawl()` function signature.

3. Pass `auth_mode=auth_mode` to `CrawlOptions.from_sources()` call (line 276-295).

4. Pass `auth=opts.auth` to `Crawler()` constructor (line 372-391).

5. Add the `auth` command group after the `mcp` command (after line 521):

```python
@cli.group()
def auth():
    """Manage authentication sessions."""
    pass


@auth.command("login")
@click.option("--config-file", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--auth-mode", type=click.Choice(["auto", "manual"]), default=None)
def auth_login(config_file, auth_mode):
    """Run login flow and save session (without crawling)."""
    import asyncio

    from ergane.auth.manager import AuthManager
    from ergane.config import CrawlOptions, load_config

    file_config = load_config(config_file)
    opts = CrawlOptions.from_sources(file_config, auth_mode=auth_mode)
    if opts.auth is None:
        raise click.ClickException("No auth section in config file")

    mgr = AuthManager(opts.auth)

    async def _login():
        import httpx
        async with httpx.AsyncClient() as client:
            await mgr.ensure_authenticated(client)
        click.echo("Login successful. Session saved.")

    asyncio.run(_login())


@auth.command("status")
@click.option("--session-file", default=".ergane_session.json")
def auth_status(session_file):
    """Check if a saved session exists and is valid."""
    from ergane.auth.session_store import SessionStore

    store = SessionStore(session_file)
    cookies = store.load()
    if cookies is None:
        click.echo("No saved session found.")
    else:
        click.echo(f"Session found with {len(cookies)} cookie(s).")


@auth.command("clear")
@click.option("--session-file", default=".ergane_session.json")
def auth_clear(session_file):
    """Delete saved session file."""
    from ergane.auth.session_store import SessionStore

    store = SessionStore(session_file)
    store.clear()
    click.echo("Session cleared.")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_auth.py -v`
Expected: All 4 tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add ergane/main.py tests/test_cli_auth.py
git commit -m "feat(auth): add --auth-mode flag and ergane auth subcommands"
```

---

### Task 8: Re-export AuthManager from Public API

**Files:**
- Modify: `ergane/__init__.py` (add AuthManager, AuthConfig to exports)
- Modify: `ergane/crawler/__init__.py` (no change needed — auth is its own package)
- Test: quick import smoke test

**Step 1: Write the failing test**

Add `tests/test_auth_exports.py`:

```python
"""Smoke test: auth classes importable from top-level ergane package."""


def test_auth_importable():
    from ergane.auth import AuthConfig, AuthenticationError, AuthManager, SessionStore

    assert AuthConfig is not None
    assert AuthenticationError is not None
    assert AuthManager is not None
    assert SessionStore is not None
```

**Step 2: Run test (should already pass since ergane.auth exists)**

Run: `uv run pytest tests/test_auth_exports.py -v`
Expected: PASS (auth module already exists from prior tasks)

**Step 3: Update top-level exports**

Modify `ergane/__init__.py` — add to imports and `__all__`:

```python
from ergane.auth import AuthConfig, AuthenticationError, AuthManager

# Add to __all__:
"AuthConfig",
"AuthenticationError",
"AuthManager",
```

**Step 4: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 5: Commit**

```bash
git add ergane/__init__.py tests/test_auth_exports.py
git commit -m "feat(auth): export auth classes from top-level ergane package"
```

---

### Task 9: Integration Test — Full Auth Round-Trip

**Files:**
- Create: `tests/test_auth_roundtrip.py`

This test verifies the full pipeline: AuthConfig → AuthManager → SessionStore → cookie injection, using mocks for Playwright (no real browser needed in CI).

**Step 1: Write the integration test**

Create `tests/test_auth_roundtrip.py`:

```python
"""Integration test: full auth round-trip with mocked Playwright."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ergane.auth.config import AuthConfig
from ergane.auth.manager import AuthManager


@pytest.fixture()
def auth_config():
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


def _mock_playwright():
    """Build a mock Playwright context that returns fake cookies."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.locator = MagicMock()

    locator = AsyncMock()
    locator.count = AsyncMock(return_value=1)
    locator.fill = AsyncMock()
    locator.click = AsyncMock()
    mock_page.locator.return_value = locator
    mock_page.wait_for_load_state = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.cookies = AsyncMock(return_value=[
        {"name": "session_id", "value": "fresh123", "domain": "example.com", "path": "/"},
    ])

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw.__aexit__ = AsyncMock(return_value=False)

    return mock_pw


class TestAuthRoundTrip:
    async def test_fresh_login_injects_cookies(self, auth_config, tmp_path):
        mgr = AuthManager(auth_config, session_dir=tmp_path)
        mock_pw = _mock_playwright()

        async with httpx.AsyncClient() as client:
            with patch("ergane.auth.manager.async_playwright", return_value=mock_pw):
                # Mock validation to succeed after login
                with patch.object(mgr, "_validate_session", return_value=True):
                    await mgr.ensure_authenticated(client)

            assert client.cookies.get("session_id") == "fresh123"

    async def test_saved_session_reused(self, auth_config, tmp_path):
        mgr = AuthManager(auth_config, session_dir=tmp_path)
        # Pre-save a session
        mgr._store.save([
            {"name": "session_id", "value": "saved456", "domain": "example.com", "path": "/"},
        ])

        async with httpx.AsyncClient() as client:
            with patch.object(mgr, "_validate_session", return_value=True):
                await mgr.ensure_authenticated(client)

            assert client.cookies.get("session_id") == "saved456"

    async def test_stale_session_triggers_relogin(self, auth_config, tmp_path):
        mgr = AuthManager(auth_config, session_dir=tmp_path)
        # Pre-save an old session
        mgr._store.save([
            {"name": "session_id", "value": "old789", "domain": "example.com", "path": "/"},
        ])

        mock_pw = _mock_playwright()
        call_count = 0

        async def validate_side_effect(client):
            nonlocal call_count
            call_count += 1
            # First call (old cookies) fails, second call (new cookies) succeeds
            return call_count > 1

        async with httpx.AsyncClient() as client:
            with patch.object(mgr, "_validate_session", side_effect=validate_side_effect):
                with patch("ergane.auth.manager.async_playwright", return_value=mock_pw):
                    await mgr.ensure_authenticated(client)

            # Should have the fresh cookies from re-login
            assert client.cookies.get("session_id") == "fresh123"
```

**Step 2: Run the integration test**

Run: `uv run pytest tests/test_auth_roundtrip.py -v`
Expected: All 3 tests PASS

**Step 3: Commit**

```bash
git add tests/test_auth_roundtrip.py
git commit -m "test(auth): add integration tests for full auth round-trip"
```

---

### Task 10: Lint, Full Test Suite, Final Commit

**Step 1: Run linter**

Run: `uv run ruff check ergane/auth/ tests/test_auth*.py`
Expected: No violations (or only pre-existing UP006/UP035 warnings)

**Step 2: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass (existing + new auth tests)

**Step 3: Fix any issues found**

Address any lint or test failures.

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(auth): address lint and test issues"
```

**Step 5: Verify clean state**

Run: `uv run ruff check ergane/ tests/ && uv run pytest tests/ -q`
Expected: Clean lint + all tests pass
