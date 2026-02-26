# Ergane Optimizations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the three-phase optimization plan from the design doc, eliminating idle sleeps, per-call parsing overhead, lock contention, and memory spikes on large crawls.

**Architecture:** Phase 1 applies isolated quick wins (caching, batch locking, WAL, event-driven workers). Phase 2 rewrites the engine's polling loop to be event-driven. Phase 3 adds scale/DX improvements (streaming pipeline consolidation, per-domain rate limits, MCP progress, benchmarks). Each task ends with a commit; tests must pass before moving on.

**Tech Stack:** Python 3.10+, asyncio, httpx, selectolax, Pydantic v2, Polars, SQLite (stdlib), pytest-asyncio (`asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed), uv (`uv run pytest tests/ -q`).

---

## Phase 1 — Quick Wins

---

### Task 1: Cache `SchemaConfig.from_model`

**Files:**
- Modify: `ergane/schema/base.py`
- Test: `tests/test_schema.py`

**Step 1: Write the failing test**

Add to `tests/test_schema.py` (inside a new `TestSchemaConfigCaching` class at the bottom):

```python
class TestSchemaConfigCaching:
    """SchemaConfig.from_model should be cached across calls."""

    def test_from_model_returns_same_object(self):
        """Calling from_model twice on the same class returns the identical object."""
        from ergane.schema.base import SchemaConfig

        class _CacheTestModel(BaseModel):
            title: str = selector("h1")

        first = SchemaConfig.from_model(_CacheTestModel)
        second = SchemaConfig.from_model(_CacheTestModel)
        assert first is second

    def test_different_models_cached_independently(self):
        """Two different model classes each get their own cached config."""
        from ergane.schema.base import SchemaConfig

        class _ModelA(BaseModel):
            title: str = selector("h1")

        class _ModelB(BaseModel):
            price: str = selector(".price")

        assert SchemaConfig.from_model(_ModelA) is not SchemaConfig.from_model(_ModelB)
        assert SchemaConfig.from_model(_ModelA) is SchemaConfig.from_model(_ModelA)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_schema.py::TestSchemaConfigCaching -v
```

Expected: `FAILED` — `first is second` assertion fails (two distinct objects).

**Step 3: Implement**

In `ergane/schema/base.py`, add `import functools` at the top and extract the build logic to a module-level cached function:

```python
import functools

# ... existing dataclass definitions ...

@functools.cache
def _build_schema_config(model: type[BaseModel]) -> "SchemaConfig":
    """Build and cache a SchemaConfig for a Pydantic model class.

    Cached because model classes are immutable — re-parsing field annotations
    on every page fetch is pure waste.
    """
    cached: dict[str, FieldConfig] | None = getattr(model, "__ergane_fields__", None)
    if cached is not None:
        return SchemaConfig(model=model, fields=dict(cached))

    config = SchemaConfig(model=model)
    for field_name, field_info in model.model_fields.items():
        field_config = SchemaConfig._parse_field(field_name, field_info)
        config.fields[field_name] = field_config
    return config
```

Then replace `SchemaConfig.from_model` body to delegate:

```python
@classmethod
def from_model(cls, model: type[BaseModel]) -> "SchemaConfig":
    return _build_schema_config(model)
```

Remove the logic that was previously inside `from_model` (it now lives in `_build_schema_config`).

**Step 4: Run tests**

```bash
uv run pytest tests/test_schema.py -v
```

Expected: all pass including the two new caching tests.

**Step 5: Full suite check**

```bash
uv run pytest tests/ -q
```

Expected: all tests pass.

**Step 6: Commit**

```bash
git add ergane/schema/base.py tests/test_schema.py
git commit -m "perf: cache SchemaConfig.from_model to avoid per-page re-parsing"
```

---

### Task 2: Batch scheduler lock in `add_many`

**Files:**
- Modify: `ergane/crawler/scheduler.py`
- Test: `tests/test_scheduler.py`

**Step 1: Write the failing test**

Add to `tests/test_scheduler.py` (in a new `TestAddManyBatching` class):

```python
class TestAddManyBatching:
    """add_many correctness and dedup behaviour."""

    async def test_add_many_deduplicates_within_batch(self, scheduler: Scheduler):
        """Duplicates within the same add_many call are rejected."""
        requests = [
            CrawlRequest(url="https://example.com/a"),
            CrawlRequest(url="https://example.com/a"),  # duplicate
            CrawlRequest(url="https://example.com/b"),
        ]
        added = await scheduler.add_many(requests)
        assert added == 2
        assert await scheduler.size() == 2

    async def test_add_many_deduplicates_against_seen(self, scheduler: Scheduler):
        """URLs already seen via add() are rejected by add_many."""
        await scheduler.add(CrawlRequest(url="https://example.com/a"))
        added = await scheduler.add_many([
            CrawlRequest(url="https://example.com/a"),  # already seen
            CrawlRequest(url="https://example.com/b"),
        ])
        assert added == 1
        assert await scheduler.size() == 2  # original + new

    async def test_add_many_returns_count(self, scheduler: Scheduler):
        """add_many returns number of URLs actually enqueued."""
        requests = [CrawlRequest(url=f"https://example.com/{i}") for i in range(5)]
        added = await scheduler.add_many(requests)
        assert added == 5
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_scheduler.py::TestAddManyBatching -v
```

Expected: `FAILED` — `test_add_many_deduplicates_within_batch` fails because the current loop-based implementation does not deduplicate *within* a single `add_many` call (each `add()` call checks `_seen` but the second duplicate is added to `_seen` by the first iteration before the second check runs — actually it should pass, let me re-examine).

Actually the current implementation DOES deduplicate because `add()` adds to `_seen` before returning. So the `within_batch` test may already pass. The key new test is the correctness under the refactor. Run the tests to confirm current behaviour, then proceed with the implementation.

```bash
uv run pytest tests/test_scheduler.py -v
```

**Step 3: Implement**

Replace `add_many` in `ergane/crawler/scheduler.py`:

```python
async def add_many(self, requests: list[CrawlRequest]) -> int:
    """Add multiple URLs atomically under a single lock acquisition."""
    added = 0
    notify = False
    async with self._lock:
        for req in requests:
            normalized = self._normalize_url(req.url)
            if normalized in self._seen:
                continue
            if len(self._queue) >= self.config.max_queue_size:
                _logger.warning(
                    "Queue full (%d), dropping URL: %s",
                    self.config.max_queue_size,
                    req.url,
                )
                continue
            if len(self._seen) >= _MAX_SEEN_URLS:
                evict_keys = list(self._seen.keys())[:_EVICT_BATCH]
                domain_counts = Counter(urlparse(k).netloc for k in evict_keys)
                top_domains_str = ", ".join(
                    f"{d}({c})" for d, c in domain_counts.most_common(3)
                )
                for k in evict_keys:
                    del self._seen[k]
                _logger.warning(
                    "URL seen-set capped at %d; evicted %d oldest entries "
                    "(top domains in evicted batch: %s)",
                    _MAX_SEEN_URLS,
                    _EVICT_BATCH,
                    top_domains_str,
                )
            self._seen[normalized] = None
            self._counter += 1
            heapq.heappush(
                self._queue,
                (-req.priority, self._counter, req),
            )
            added += 1
            notify = True
    if notify:
        self._not_empty.set()
    return added
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: all pass.

**Step 5: Full suite check**

```bash
uv run pytest tests/ -q
```

**Step 6: Commit**

```bash
git add ergane/crawler/scheduler.py tests/test_scheduler.py
git commit -m "perf: batch scheduler lock in add_many (single acquire for N URLs)"
```

---

### Task 3: SQLite cache — WAL mode + persistent connection

**Files:**
- Modify: `ergane/crawler/cache.py`
- Test: `tests/test_cache.py`

**Step 1: Write the failing test**

Add to `tests/test_cache.py` (new `TestCacheWAL` class):

```python
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
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_cache.py::TestCacheWAL -v
```

Expected: `FAILED` — WAL pragma returns `"delete"` (the default).

**Step 3: Implement**

Replace `ResponseCache.__init__` and `_init_db` in `ergane/crawler/cache.py`:

```python
import threading

class ResponseCache:
    def __init__(self, cache_dir: Path, ttl_seconds: int = 3600):
        self.cache_dir = cache_dir
        self.ttl = timedelta(seconds=ttl_seconds)
        self.db_path = cache_dir / "response_cache.db"
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()
        self._cleanup_expired_sync()

    def _init_db(self) -> None:
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
```

Update `_get_sync`, `_set_sync`, `_delete_sync`, `_clear_sync`, `_cleanup_expired_sync` to use `self._conn` under `self._lock` instead of opening a new connection each time:

```python
def _get_sync(self, url: str) -> CacheEntry | None:
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
    url_hash = self._hash_url(url)
    with self._lock:
        self._conn.execute("DELETE FROM responses WHERE url_hash = ?", (url_hash,))
        self._conn.commit()

def _clear_sync(self) -> None:
    with self._lock:
        self._conn.execute("DELETE FROM responses")
        self._conn.commit()

def _cleanup_expired_sync(self) -> int:
    cutoff = (datetime.now(timezone.utc) - self.ttl).isoformat()
    with self._lock:
        cursor = self._conn.execute(
            "DELETE FROM responses WHERE cached_at < ?", (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_cache.py -v
```

Expected: all pass including the two new WAL tests.

**Step 5: Full suite check**

```bash
uv run pytest tests/ -q
```

**Step 6: Commit**

```bash
git add ergane/crawler/cache.py tests/test_cache.py
git commit -m "perf: SQLite cache uses WAL mode and persistent connection"
```

---

### Task 4: Event-driven worker idle path

**Files:**
- Modify: `ergane/crawler/scheduler.py`
- Modify: `ergane/crawler/engine.py`
- Test: `tests/test_scheduler.py`

**Step 1: Write the failing test**

Add to `tests/test_scheduler.py`:

```python
class TestWaitNotEmpty:
    """Scheduler.wait_not_empty wakes workers when URLs arrive."""

    async def test_wait_not_empty_resolves_when_url_added(self, scheduler: Scheduler):
        """wait_not_empty() returns once a URL is enqueued."""
        async def _add_later():
            await asyncio.sleep(0.05)
            await scheduler.add(CrawlRequest(url="https://example.com/wake"))

        asyncio.create_task(_add_later())
        # Should return within ~0.1s once the URL is added
        await asyncio.wait_for(scheduler.wait_not_empty(), timeout=1.0)
        assert await scheduler.size() == 1

    async def test_wait_not_empty_immediate_if_already_has_items(
        self, scheduler: Scheduler
    ):
        """wait_not_empty() returns immediately when queue is non-empty."""
        await scheduler.add(CrawlRequest(url="https://example.com/1"))
        # Should not block at all
        await asyncio.wait_for(scheduler.wait_not_empty(), timeout=0.1)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_scheduler.py::TestWaitNotEmpty -v
```

Expected: `AttributeError: 'Scheduler' object has no attribute 'wait_not_empty'`

**Step 3: Add `wait_not_empty` to Scheduler**

In `ergane/crawler/scheduler.py`, add after `is_empty`:

```python
async def wait_not_empty(self) -> None:
    """Wait until at least one URL is in the queue.

    Returns immediately if the queue already has items. Intended for
    workers to replace ``asyncio.sleep(0.1)`` with an event-driven wait.
    """
    await self._not_empty.wait()
```

**Step 4: Update worker idle path in engine**

In `ergane/crawler/engine.py`, inside `_worker`, replace the idle-path sleep:

```python
# Before:
await asyncio.sleep(0.1)
continue

# After:
try:
    await asyncio.wait_for(scheduler.wait_not_empty(), timeout=0.5)
except asyncio.TimeoutError:
    pass
continue
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_scheduler.py tests/test_engine.py -v
```

Expected: all pass.

**Step 6: Full suite check**

```bash
uv run pytest tests/ -q
```

**Step 7: Commit**

```bash
git add ergane/crawler/scheduler.py ergane/crawler/engine.py tests/test_scheduler.py
git commit -m "perf: event-driven worker idle path via Scheduler.wait_not_empty"
```

---

## Phase 2 — Event-Driven Engine Loop

---

### Task 5: Replace polling sleep with `asyncio.wait_for` item drain

**Files:**
- Modify: `ergane/crawler/engine.py`
- Test: `tests/test_engine.py`

**Step 1: Write the failing test**

Add to `tests/test_engine.py` (new `TestStreamLatency` class):

```python
class TestStreamLatency:
    """Items should be yielded promptly, not held up by a polling interval."""

    async def test_stream_yields_within_200ms(self, mock_server: str):
        """First item from stream() arrives well under 200ms after crawl starts."""
        import time

        url = f"{mock_server}/"
        start = time.monotonic()
        first_item_time = None

        async with Crawler(
            urls=[url],
            max_pages=1,
            same_domain=False,
            respect_robots_txt=False,
        ) as crawler:
            async for _item in crawler.stream():
                first_item_time = time.monotonic() - start
                break

        assert first_item_time is not None
        assert first_item_time < 0.2, (
            f"First item took {first_item_time:.3f}s — polling loop not event-driven?"
        )
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine.py::TestStreamLatency -v
```

Expected: `FAILED` — item latency is ~100ms due to the polling sleep.

**Step 3: Implement**

In `ergane/crawler/engine.py`, inside `_crawl_iter`, locate the existing drain+sleep block:

```python
# Drain any available items from the queue
while not item_queue.empty():
    yield item_queue.get_nowait()

await asyncio.sleep(0.1)
```

Replace with:

```python
try:
    item = await asyncio.wait_for(item_queue.get(), timeout=0.1)
    yield item
except asyncio.TimeoutError:
    pass
```

The `finally` block's drain (`while not item_queue.empty(): yield item_queue.get_nowait()`) and the shutdown drain after `asyncio.gather` stay unchanged.

**Step 4: Run tests**

```bash
uv run pytest tests/test_engine.py -v
```

Expected: all pass including `TestStreamLatency`.

**Step 5: Full suite check**

```bash
uv run pytest tests/ -q
```

**Step 6: Commit**

```bash
git add ergane/crawler/engine.py tests/test_engine.py
git commit -m "perf: event-driven engine loop — yield items immediately via wait_for"
```

---

## Phase 3 — Scale & DX

---

### Task 6: Memory-bounded pipeline consolidation

**Files:**
- Modify: `ergane/crawler/pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing tests**

Add to `tests/test_pipeline.py` (new `TestStreamingConsolidation` class):

```python
class TestStreamingConsolidation:
    """Non-parquet formats consolidate without loading all data into RAM."""

    def _make_pipeline(
        self, config: CrawlConfig, tmp_path: Path, filename: str
    ) -> Pipeline:
        out = tmp_path / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        return Pipeline(config, out)

    async def _fill_pipeline(self, pipeline: Pipeline, n: int) -> None:
        for i in range(n):
            await pipeline.add(make_item(f"https://example.com/{i}", f"Title {i}"))
        await pipeline.flush()

    async def test_jsonl_consolidate_no_dataframe(
        self, config: CrawlConfig, tmp_path: Path
    ):
        """JSONL consolidation produces correct line count without in-memory concat."""
        p = self._make_pipeline(config, tmp_path, "out.jsonl")
        config = CrawlConfig(batch_size=3)  # force multiple batches
        p2 = Pipeline(config, tmp_path / "out2.jsonl")
        for i in range(9):
            await p2.add(make_item(f"https://example.com/{i}"))
        await p2.flush()
        p2.consolidate()

        lines = (tmp_path / "out2.jsonl").read_text().strip().splitlines()
        assert len(lines) == 9

    async def test_csv_consolidate_single_header(
        self, config: CrawlConfig, tmp_path: Path
    ):
        """CSV consolidation writes exactly one header row."""
        cfg = CrawlConfig(batch_size=3)
        p = Pipeline(cfg, tmp_path / "out.csv")
        for i in range(9):
            await p.add(make_item(f"https://example.com/{i}"))
        await p.flush()
        p.consolidate()

        text = (tmp_path / "out.csv").read_text()
        lines = [l for l in text.splitlines() if l.strip()]
        header_count = sum(1 for l in lines if l.startswith("url,") or l.startswith('"url"'))
        assert header_count == 1
        assert len(lines) == 10  # 1 header + 9 data rows

    async def test_json_consolidate_valid_array(
        self, config: CrawlConfig, tmp_path: Path
    ):
        """JSON consolidation writes a valid JSON array."""
        import json as _json
        cfg = CrawlConfig(batch_size=3)
        p = Pipeline(cfg, tmp_path / "out.json")
        for i in range(9):
            await p.add(make_item(f"https://example.com/{i}"))
        await p.flush()
        p.consolidate()

        data = _json.loads((tmp_path / "out.json").read_text())
        assert isinstance(data, list)
        assert len(data) == 9
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_pipeline.py::TestStreamingConsolidation -v
```

Expected: tests may pass for basic correctness but the goal is to ensure the new streaming path is exercised.

**Step 3: Implement**

Add a `consolidate_batches` method to the relevant `BatchWriter` subclasses in `ergane/crawler/pipeline.py`. Also add a base implementation:

```python
import shutil

class BatchWriter(ABC):
    # ... existing methods ...

    def consolidate_batches(
        self, batch_files: list[Path], output_path: Path, stem: str
    ) -> None:
        """Merge batch files into output_path.

        Default: load all into a Polars DataFrame (in-memory). Subclasses
        override with streaming implementations for large crawls.
        """
        if not batch_files:
            return
        if len(batch_files) == 1:
            batch_files[0].replace(output_path)
            return
        dfs = [self._read(f) for f in batch_files]
        combined = pl.concat(dfs)
        if "url" in combined.columns:
            combined = combined.unique(subset=["url"], keep="last")
        suffix = output_path.suffix or ".tmp"
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, suffix=suffix, delete=False
        ) as tmp_f:
            tmp_path = Path(tmp_f.name)
        try:
            self.write_final(combined, tmp_path, stem)
            tmp_path.replace(output_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        for f in batch_files:
            f.unlink()
```

Override for `JsonlWriter`:

```python
class JsonlWriter(BatchWriter):
    # ... existing methods ...

    def consolidate_batches(
        self, batch_files: list[Path], output_path: Path, stem: str
    ) -> None:
        """Concatenate JSONL batch files without loading into RAM."""
        with open(output_path, "wb") as out:
            for f in batch_files:
                with open(f, "rb") as inp:
                    shutil.copyfileobj(inp, out)
        for f in batch_files:
            f.unlink()
```

Override for `CsvWriter`:

```python
class CsvWriter(BatchWriter):
    # ... existing methods ...

    def consolidate_batches(
        self, batch_files: list[Path], output_path: Path, stem: str
    ) -> None:
        """Concatenate CSV batches, preserving only the first header row."""
        with open(output_path, "wb") as out:
            for i, f in enumerate(batch_files):
                with open(f, "rb") as inp:
                    if i > 0:
                        inp.readline()  # discard header from batch 2+
                    shutil.copyfileobj(inp, out)
        for f in batch_files:
            f.unlink()
```

Override for `JsonWriter` (JSON array streaming):

```python
class JsonWriter(JsonlWriter):
    def consolidate_batches(
        self, batch_files: list[Path], output_path: Path, stem: str
    ) -> None:
        """Stream JSONL batches into a JSON array without loading all into RAM."""
        with open(output_path, "w", encoding="utf-8") as out:
            out.write("[\n")
            first_record = True
            for f in batch_files:
                with open(f, encoding="utf-8") as inp:
                    for line in inp:
                        line = line.strip()
                        if not line:
                            continue
                        if not first_record:
                            out.write(",\n")
                        out.write(line)
                        first_record = False
            out.write("\n]\n")
        for f in batch_files:
            f.unlink()
```

Update `Pipeline.consolidate()` to delegate to the writer:

```python
def consolidate(self) -> Path:
    stem = self.output_path.stem
    parent = self.output_path.parent
    batch_ext = self._writer.batch_extension
    batch_files = sorted(parent.glob(f"{stem}_*{batch_ext}"))

    if not batch_files:
        return self.output_path

    self._writer.consolidate_batches(batch_files, self.output_path, stem)
    return self.output_path
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_pipeline.py -v
```

Expected: all pass.

**Step 5: Full suite check**

```bash
uv run pytest tests/ -q
```

**Step 6: Commit**

```bash
git add ergane/crawler/pipeline.py tests/test_pipeline.py
git commit -m "perf: streaming pipeline consolidation for JSONL/CSV/JSON formats"
```

---

### Task 7: Per-domain rate limits

**Files:**
- Modify: `ergane/models/schemas.py`
- Modify: `ergane/crawler/fetcher.py`
- Modify: `ergane/main.py`
- Test: `tests/test_fetcher.py`

**Step 1: Write the failing test**

Add to `tests/test_fetcher.py`:

```python
class TestPerDomainRateLimits:
    """Domain-specific rate limits override the global rate."""

    def test_domain_bucket_uses_domain_rate(self):
        """_get_bucket uses domain_rate_limits when present."""
        config = CrawlConfig(
            max_requests_per_second=1.0,
            domain_rate_limits={"fast.example.com": 100.0},
        )
        fetcher = Fetcher(config)
        fast_bucket = fetcher._get_bucket("fast.example.com")
        slow_bucket = fetcher._get_bucket("slow.example.com")
        assert fast_bucket.rate == 100.0
        assert slow_bucket.rate == 1.0

    def test_domain_rate_limits_defaults_empty(self):
        """CrawlConfig has empty domain_rate_limits by default."""
        config = CrawlConfig()
        assert config.domain_rate_limits == {}
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_fetcher.py::TestPerDomainRateLimits -v
```

Expected: `AttributeError: 'CrawlConfig' object has no attribute 'domain_rate_limits'`

**Step 3: Add `domain_rate_limits` to `CrawlConfig`**

In `ergane/models/schemas.py`, add after `proxy`:

```python
domain_rate_limits: dict[str, float] = Field(
    default_factory=dict,
    description="Per-domain rate limits (req/sec). Overrides max_requests_per_second.",
)
```

**Step 4: Update `Fetcher._get_bucket`**

In `ergane/crawler/fetcher.py`:

```python
def _get_bucket(self, domain: str) -> TokenBucket:
    if domain not in self._domain_buckets:
        rate = self.config.domain_rate_limits.get(
            domain, self.config.max_requests_per_second
        )
        self._domain_buckets[domain] = TokenBucket(rate)
    return self._domain_buckets[domain]
```

**Step 5: Add CLI flag**

In `ergane/main.py`, add to the `crawl` command options (before the `@click.pass_context` or wherever other options are declared — search for the existing `--rate-limit` option and add nearby):

```python
@click.option(
    "--domain-rate-limit",
    "domain_rate_limits",
    multiple=True,
    metavar="DOMAIN:RATE",
    help="Per-domain rate limit as 'domain:rate'. Repeatable.",
)
```

In the command body, parse the tuples before building `CrawlConfig`:

```python
parsed_domain_rates: dict[str, float] = {}
for entry in domain_rate_limits:
    if ":" not in entry:
        raise click.BadParameter(f"Expected DOMAIN:RATE, got: {entry!r}")
    domain, _, rate_str = entry.partition(":")
    try:
        parsed_domain_rates[domain.strip()] = float(rate_str.strip())
    except ValueError:
        raise click.BadParameter(f"Rate must be a number, got: {rate_str!r}")
```

Then pass `domain_rate_limits=parsed_domain_rates` to `CrawlConfig`.

**Step 6: Run tests**

```bash
uv run pytest tests/test_fetcher.py tests/test_config.py -v
```

Expected: all pass.

**Step 7: Full suite check**

```bash
uv run pytest tests/ -q
```

**Step 8: Commit**

```bash
git add ergane/models/schemas.py ergane/crawler/fetcher.py ergane/main.py tests/test_fetcher.py
git commit -m "feat: per-domain rate limits via CrawlConfig.domain_rate_limits and --domain-rate-limit CLI flag"
```

---

### Task 8: MCP crawl progress reporting

**Files:**
- Modify: `ergane/mcp/tools.py`
- Test: `tests/test_mcp.py`

**Step 1: Understand the existing crawl tool**

Read `ergane/mcp/tools.py` and find the `crawl` tool function (search for `async def crawl` or `@mcp.tool`). Identify the line that calls `crawler.run()`.

**Step 2: Write the failing test**

First check what test infrastructure exists in `tests/test_mcp.py` for the crawl tool, then add:

```python
class TestCrawlProgress:
    """MCP crawl tool emits progress during execution."""

    async def test_crawl_uses_stream_not_run(self, mock_server: str):
        """The crawl tool iterates stream() so progress can be reported."""
        # This is a smoke test — we verify the tool completes successfully
        # and returns items (progress is reported internally to the MCP context).
        from ergane.mcp.tools import register_tools
        from unittest.mock import AsyncMock, MagicMock
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register_tools(app)

        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        # Locate and call the crawl tool handler directly
        # (exact approach depends on FastMCP's internal API — adjust as needed)
        # The key assertion: report_progress was called at least once.
        # (Implement after inspecting actual tool registration pattern in tools.py)
```

> **Note:** The exact test structure depends on how tools are registered in `tools.py`. Read the file first and adjust the test to match the registration pattern used by other MCP tests in `test_mcp.py`.

**Step 3: Implement**

In `ergane/mcp/tools.py`, find the `crawl` tool and change `crawler.run()` to `crawler.stream()`:

```python
# Before (approximately):
results = await crawler.run()

# After:
results = []
pages_crawled = 0
async for item in crawler.stream():
    results.append(item)
    pages_crawled += 1
    await ctx.report_progress(pages_crawled, max_pages)
```

Make sure `ctx` is in scope — it's passed as a parameter to FastMCP tools via `Context` injection. Check the existing tool signature and add `ctx: Context` if not already present.

**Step 4: Run tests**

```bash
uv run pytest tests/test_mcp.py -v
```

Expected: all pass.

**Step 5: Full suite check**

```bash
uv run pytest tests/ -q
```

**Step 6: Commit**

```bash
git add ergane/mcp/tools.py tests/test_mcp.py
git commit -m "feat: MCP crawl tool reports progress via ctx.report_progress during stream"
```

---

### Task 9: Benchmarks

**Files:**
- Create: `benchmarks/run.py`
- Create: `benchmarks/__init__.py` (empty)

**Step 1: Create `benchmarks/__init__.py`**

Empty file.

**Step 2: Create `benchmarks/run.py`**

```python
#!/usr/bin/env python
"""Ergane performance benchmark.

Spins up a local HTTP server with synthetic link graph, runs a timed crawl,
and prints throughput metrics. Run with:

    uv run python benchmarks/run.py [--pages N] [--concurrency N]
"""

from __future__ import annotations

import asyncio
import sys
import time
import tracemalloc
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


# ---------------------------------------------------------------------------
# Synthetic site generator
# ---------------------------------------------------------------------------

def _build_pages(n: int) -> dict[str, bytes]:
    """Build N interlinked HTML pages for crawling."""
    pages: dict[str, bytes] = {}
    for i in range(n):
        links = "".join(
            f'<a href="/page/{j}">page {j}</a> '
            for j in range(max(0, i - 2), min(n, i + 3))
            if j != i
        )
        html = (
            f"<html><head><title>Page {i}</title></head>"
            f"<body><h1>Page {i}</h1>{links}</body></html>"
        ).encode()
        pages[f"/page/{i}"] = html
    # index page links to first 10
    index_links = "".join(f'<a href="/page/{i}">page {i}</a> ' for i in range(min(10, n)))
    pages["/"] = (
        f"<html><head><title>Index</title></head>"
        f"<body><h1>Index</h1>{index_links}</body></html>"
    ).encode()
    return pages


class _BenchHandler(BaseHTTPRequestHandler):
    pages: dict[str, bytes] = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/robots.txt":
            self.send_response(404)
            self.end_headers()
            return
        body = self.pages.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

async def run_benchmark(n_pages: int = 200, concurrency: int = 20) -> dict:
    from ergane.crawler.engine import Crawler

    _BenchHandler.pages = _build_pages(n_pages)
    server = HTTPServer(("127.0.0.1", 0), _BenchHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/"
    tracemalloc.start()

    start = time.monotonic()
    items = 0
    async with Crawler(
        urls=[url],
        max_pages=n_pages,
        concurrency=concurrency,
        rate_limit=1000.0,
        same_domain=True,
        respect_robots_txt=False,
    ) as crawler:
        async for _ in crawler.stream():
            items += 1
    elapsed = time.monotonic() - start

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    server.shutdown()

    pages_crawled = crawler.pages_crawled
    return {
        "pages_crawled": pages_crawled,
        "items_extracted": items,
        "elapsed_s": round(elapsed, 3),
        "pages_per_sec": round(pages_crawled / max(elapsed, 0.001), 1),
        "items_per_sec": round(items / max(elapsed, 0.001), 1),
        "peak_memory_mb": round(peak / 1024 / 1024, 2),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ergane benchmark")
    parser.add_argument("--pages", type=int, default=200, help="Pages to crawl")
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    print(f"Benchmarking: {args.pages} pages, concurrency={args.concurrency}")
    results = asyncio.run(run_benchmark(args.pages, args.concurrency))

    print("\nResults:")
    for k, v in results.items():
        print(f"  {k:<22} {v}")


if __name__ == "__main__":
    main()
```

**Step 3: Run the benchmark to establish a baseline**

```bash
uv run python benchmarks/run.py --pages 200 --concurrency 20
```

Expected output (values will vary):
```
Benchmarking: 200 pages, concurrency=20

Results:
  pages_crawled          200
  items_extracted        200
  elapsed_s              X.XXX
  pages_per_sec          XXX.X
  items_per_sec          XXX.X
  peak_memory_mb         XX.XX
```

Record the baseline numbers in a comment at the top of the file.

**Step 4: Verify it also runs after all optimizations**

```bash
uv run python benchmarks/run.py --pages 500 --concurrency 20
```

Expected: completes without error.

**Step 5: Commit**

```bash
git add benchmarks/
git commit -m "feat: add benchmarks/run.py for crawl throughput measurement"
```

---

## Final Verification

```bash
uv run pytest tests/ -q
uv run ruff check ergane/ tests/
uv run python benchmarks/run.py --pages 200
```

All tests pass, no new lint errors, benchmark runs cleanly.
