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
