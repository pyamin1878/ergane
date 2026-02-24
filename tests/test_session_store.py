"""Tests for ergane.auth.session_store.SessionStore."""

import base64
import hashlib
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
        from cryptography.fernet import Fernet

        key = base64.urlsafe_b64encode(hashlib.sha256(b"test-key").digest())
        f = Fernet(key)
        raw = store._session_file.read_bytes()
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
