"""Tests for auth wiring into CrawlOptions and CrawlConfig."""

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
