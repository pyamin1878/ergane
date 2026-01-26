"""SQLite-based response caching for development and debugging."""

import hashlib
import json
import sqlite3
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
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS responses (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT,
                    status_code INTEGER,
                    content TEXT,
                    headers TEXT,
                    cached_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cached_at ON responses(cached_at)
            """)

    def _hash_url(self, url: str) -> str:
        """Generate a SHA-256 hash of the URL."""
        return hashlib.sha256(url.encode()).hexdigest()

    async def get(self, url: str) -> CacheEntry | None:
        """Retrieve a cached response if it exists and hasn't expired.

        Args:
            url: The URL to look up.

        Returns:
            CacheEntry if found and valid, None otherwise.
        """
        url_hash = self._hash_url(url)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT url, status_code, content, headers, cached_at
                FROM responses WHERE url_hash = ?
                """,
                (url_hash,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        cached_at = datetime.fromisoformat(row[4])
        if datetime.now(timezone.utc) - cached_at > self.ttl:
            # Entry has expired
            await self.delete(url)
            return None

        return CacheEntry(
            url=row[0],
            status_code=row[1],
            content=row[2],
            headers=json.loads(row[3]),
            cached_at=cached_at,
        )

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
        url_hash = self._hash_url(url)
        cached_at = datetime.now(timezone.utc).isoformat()
        headers_json = json.dumps(headers)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO responses
                (url_hash, url, status_code, content, headers, cached_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (url_hash, url, status_code, content, headers_json, cached_at),
            )

    async def delete(self, url: str) -> None:
        """Delete a cached entry.

        Args:
            url: The URL to delete from cache.
        """
        url_hash = self._hash_url(url)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM responses WHERE url_hash = ?", (url_hash,))

    async def clear(self) -> None:
        """Clear all cached responses."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM responses")

    async def cleanup_expired(self) -> int:
        """Remove all expired entries from the cache.

        Returns:
            Number of entries removed.
        """
        cutoff = (datetime.now(timezone.utc) - self.ttl).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM responses WHERE cached_at < ?", (cutoff,)
            )
            return cursor.rowcount

    def stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dict with 'total_entries' and 'db_size_bytes' keys.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM responses")
            total = cursor.fetchone()[0]

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "total_entries": total,
            "db_size_bytes": db_size,
        }
