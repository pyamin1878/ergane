"""Smoke test: auth classes importable from top-level ergane package."""


def test_auth_importable_from_subpackage():
    from ergane.auth import AuthConfig, AuthenticationError, AuthManager, SessionStore

    assert AuthConfig is not None
    assert AuthenticationError is not None
    assert AuthManager is not None
    assert SessionStore is not None


def test_auth_importable_from_toplevel():
    from ergane import AuthConfig, AuthenticationError, AuthManager

    assert AuthConfig is not None
    assert AuthenticationError is not None
    assert AuthManager is not None
