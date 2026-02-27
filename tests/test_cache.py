"""Tests for SQLite-based response caching."""

import asyncio
from pathlib import Path

import pytest

from ergane.crawler.cache import ResponseCache


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Temporary directory for cache database."""
    return tmp_path / "cache"


@pytest.fixture
def cache(cache_dir: Path) -> ResponseCache:
    """ResponseCache with 1-hour TTL."""
    return ResponseCache(cache_dir, ttl_seconds=3600)


class TestCacheInit:
    """Cache initialization tests."""

    def test_creates_directory(self, tmp_path: Path):
        """Test that cache creates its directory if missing."""
        cache_dir = tmp_path / "nonexistent" / "nested"
        ResponseCache(cache_dir)
        assert cache_dir.exists()
        assert (cache_dir / "response_cache.db").exists()

    def test_db_created(self, cache: ResponseCache, cache_dir: Path):
        """Test that SQLite database file is created."""
        assert (cache_dir / "response_cache.db").exists()


class TestBasicCRUD:
    """Basic create, read, update, delete operations."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache: ResponseCache):
        """Test storing and retrieving a response."""
        await cache.set(
            "https://example.com/page",
            200,
            "<html>content</html>",
            {"content-type": "text/html"},
        )

        entry = await cache.get("https://example.com/page")
        assert entry is not None
        assert entry.url == "https://example.com/page"
        assert entry.status_code == 200
        assert entry.content == "<html>content</html>"
        assert entry.headers == {"content-type": "text/html"}

    @pytest.mark.asyncio
    async def test_get_missing(self, cache: ResponseCache):
        """Test that missing URLs return None."""
        entry = await cache.get("https://example.com/nonexistent")
        assert entry is None

    @pytest.mark.asyncio
    async def test_delete(self, cache: ResponseCache):
        """Test deleting a cached entry."""
        await cache.set("https://example.com/page", 200, "content", {})
        await cache.delete("https://example.com/page")
        entry = await cache.get("https://example.com/page")
        assert entry is None

    @pytest.mark.asyncio
    async def test_clear(self, cache: ResponseCache):
        """Test clearing all entries."""
        await cache.set("https://example.com/1", 200, "a", {})
        await cache.set("https://example.com/2", 200, "b", {})
        await cache.clear()

        assert await cache.get("https://example.com/1") is None
        assert await cache.get("https://example.com/2") is None

    @pytest.mark.asyncio
    async def test_upsert(self, cache: ResponseCache):
        """Test that setting the same URL overwrites the old entry."""
        await cache.set("https://example.com/page", 200, "old", {})
        await cache.set("https://example.com/page", 200, "new", {})

        entry = await cache.get("https://example.com/page")
        assert entry is not None
        assert entry.content == "new"


class TestTTLExpiration:
    """TTL and expiration tests."""

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none(self, cache_dir: Path):
        """Test that expired entries are not returned."""
        cache = ResponseCache(cache_dir, ttl_seconds=0)  # Instant expiry
        await cache.set("https://example.com/page", 200, "content", {})

        # Small delay to ensure expiry
        await asyncio.sleep(0.05)
        entry = await cache.get("https://example.com/page")
        assert entry is None

    @pytest.mark.asyncio
    async def test_valid_entry_returned(self, cache: ResponseCache):
        """Test that non-expired entries are returned."""
        await cache.set("https://example.com/page", 200, "content", {})
        entry = await cache.get("https://example.com/page")
        assert entry is not None
        assert entry.content == "content"


class TestCleanup:
    """Expired entry cleanup tests."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self, cache_dir: Path):
        """Test that cleanup removes expired entries."""
        cache = ResponseCache(cache_dir, ttl_seconds=0)
        await cache.set("https://example.com/1", 200, "a", {})
        await cache.set("https://example.com/2", 200, "b", {})

        await asyncio.sleep(0.05)
        removed = await cache.cleanup_expired()
        assert removed == 2

    @pytest.mark.asyncio
    async def test_cleanup_preserves_valid(self, cache: ResponseCache):
        """Test that cleanup preserves non-expired entries."""
        await cache.set("https://example.com/page", 200, "content", {})
        removed = await cache.cleanup_expired()
        assert removed == 0

        stats = cache.stats()
        assert stats["total_entries"] == 1


class TestStats:
    """Cache statistics tests."""

    def test_empty_stats(self, cache: ResponseCache):
        """Test stats on empty cache."""
        stats = cache.stats()
        assert stats["total_entries"] == 0
        assert stats["db_size_bytes"] > 0  # DB file exists even when empty

    @pytest.mark.asyncio
    async def test_stats_after_inserts(self, cache: ResponseCache):
        """Test stats reflect inserted entries."""
        await cache.set("https://example.com/1", 200, "a", {})
        await cache.set("https://example.com/2", 200, "b", {})

        stats = cache.stats()
        assert stats["total_entries"] == 2
        assert stats["db_size_bytes"] > 0


class TestURLHashing:
    """URL hashing consistency tests."""

    def test_same_url_same_hash(self, cache: ResponseCache):
        """Test that the same URL always produces the same hash."""
        h1 = cache._hash_url("https://example.com/page")
        h2 = cache._hash_url("https://example.com/page")
        assert h1 == h2

    def test_different_urls_different_hashes(self, cache: ResponseCache):
        """Test that different URLs produce different hashes."""
        h1 = cache._hash_url("https://example.com/page1")
        h2 = cache._hash_url("https://example.com/page2")
        assert h1 != h2

    def test_hash_is_hex_string(self, cache: ResponseCache):
        """Test that hash is a valid hex string."""
        h = cache._hash_url("https://example.com")
        assert len(h) == 64  # SHA-256 hex digest length
        assert all(c in "0123456789abcdef" for c in h)


import sqlite3 as _sqlite3


class TestCacheWAL:
    """WAL journal mode and persistent connection tests."""

    def test_wal_mode_enabled(self, cache: ResponseCache):
        """Cache database uses WAL journal mode."""
        with _sqlite3.connect(cache.db_path) as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    async def test_concurrent_reads_do_not_raise(self, cache: ResponseCache):
        """Multiple async gets on the same key complete without error."""
        await cache.set("https://example.com/x", 200, "<html/>", {})
        results = await asyncio.gather(
            cache.get("https://example.com/x"),
            cache.get("https://example.com/x"),
            cache.get("https://example.com/x"),
        )
        assert all(r is not None for r in results)
