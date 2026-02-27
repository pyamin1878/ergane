"""SQLite-based response caching for development and debugging."""

import asyncio
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class CacheEntry:
    """A cached HTTP response."""

    url: str
    status_code: int
    content: str
    headers: dict[str, str]
    cached_at: datetime


class ResponseCache:
    """SQLite-backed response cache with TTL support."""

    def __init__(self, cache_dir: Path, ttl_seconds: int = 3600):
        """Initialize the cache.

        Args:
            cache_dir: Directory to store the cache database.
            ttl_seconds: Time-to-live for cached entries in seconds.
        """
        self.cache_dir = cache_dir
        self.ttl = timedelta(seconds=ttl_seconds)
        self.db_path = cache_dir / "response_cache.db"
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()
        self._cleanup_expired_sync()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS responses (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT,
                    status_code INTEGER,
                    content TEXT,
                    headers TEXT,
                    cached_at TEXT
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cached_at ON responses(cached_at)
            """)

    def _hash_url(self, url: str) -> str:
        """Generate a SHA-256 hash of the URL."""
        return hashlib.sha256(url.encode()).hexdigest()

    def _get_sync(self, url: str) -> CacheEntry | None:
        """Synchronous cache lookup (runs in thread pool)."""
        url_hash = self._hash_url(url)
        with self._lock:
            cursor = self._conn.execute(
                "SELECT url, status_code, content, headers, cached_at "
                "FROM responses WHERE url_hash = ?",
                (url_hash,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        cached_at = datetime.fromisoformat(row[4])
        if datetime.now(timezone.utc) - cached_at > self.ttl:
            # Entry has expired — delete inline
            self._delete_sync(url)
            return None

        return CacheEntry(
            url=row[0],
            status_code=row[1],
            content=row[2],
            headers=json.loads(row[3]),
            cached_at=cached_at,
        )

    def _set_sync(
        self, url: str, status_code: int, content: str, headers_json: str
    ) -> None:
        """Synchronous cache write (runs in thread pool)."""
        url_hash = self._hash_url(url)
        cached_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses "
                "(url_hash, url, status_code, content, headers, cached_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (url_hash, url, status_code, content, headers_json, cached_at),
            )
            self._conn.commit()

    def _delete_sync(self, url: str) -> None:
        """Synchronous cache delete (runs in thread pool)."""
        url_hash = self._hash_url(url)
        with self._lock:
            self._conn.execute("DELETE FROM responses WHERE url_hash = ?", (url_hash,))
            self._conn.commit()

    def _clear_sync(self) -> None:
        """Synchronous cache clear (runs in thread pool)."""
        with self._lock:
            self._conn.execute("DELETE FROM responses")
            self._conn.commit()

    def _cleanup_expired_sync(self) -> int:
        """Synchronous expired entry cleanup (runs in thread pool or at init)."""
        cutoff = (datetime.now(timezone.utc) - self.ttl).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM responses WHERE cached_at < ?", (cutoff,)
            )
            self._conn.commit()
            return cursor.rowcount

    async def get(self, url: str) -> CacheEntry | None:
        """Retrieve a cached response if it exists and hasn't expired.

        Args:
            url: The URL to look up.

        Returns:
            CacheEntry if found and valid, None otherwise.
        """
        return await asyncio.to_thread(self._get_sync, url)

    async def set(
        self, url: str, status_code: int, content: str, headers: dict[str, str]
    ) -> None:
        """Store a response in the cache.

        Args:
            url: The URL that was fetched.
            status_code: HTTP status code.
            content: Response body content.
            headers: Response headers.
        """
        headers_json = json.dumps(headers)
        await asyncio.to_thread(self._set_sync, url, status_code, content, headers_json)

    async def delete(self, url: str) -> None:
        """Delete a cached entry.

        Args:
            url: The URL to delete from cache.
        """
        await asyncio.to_thread(self._delete_sync, url)

    async def clear(self) -> None:
        """Clear all cached responses."""
        await asyncio.to_thread(self._clear_sync)

    async def cleanup_expired(self) -> int:
        """Remove all expired entries from the cache.

        Returns:
            Number of entries removed.
        """
        return await asyncio.to_thread(self._cleanup_expired_sync)

    def stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dict with 'total_entries' and 'db_size_bytes' keys.
        """
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM responses")
            total = cursor.fetchone()[0]

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "total_entries": total,
            "db_size_bytes": db_size,
        }
