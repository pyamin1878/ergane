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
            mode="manual",
            username="${TEST_USER}",
            password="${TEST_PASS}",
        )
        assert cfg.username == "alice"
        assert cfg.password == "secret123"

    def test_env_var_missing_left_as_is(self):
        cfg = AuthConfig(
            login_url="https://example.com/login",
            mode="manual",
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
