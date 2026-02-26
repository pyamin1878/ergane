# Ergane Optimizations Design

**Date:** 2026-02-26
**Status:** Approved

## Overview

Three-phase optimization plan targeting performance, reliability at scale, and developer
experience. Each phase ships independently with passing tests before the next begins.

---

## Phase 1 — Quick Wins

Low-risk, isolated changes. All are one- to ten-line fixes with immediate measurable gains.

### 1a. SchemaExtractor caching

**Problem:** `SchemaConfig.from_model(model)` re-parses all Pydantic field annotations on
every page fetch. For a 1000-page typed-schema crawl this runs 1000 times on identical input.

**Fix:** Apply `@functools.cache` to `SchemaConfig.from_model`. The model class is a Python
`type` — immutable and hashable — making it a perfect cache key. Zero engine changes required.

**Files:** `ergane/schema/base.py`

### 1b. Scheduler batch lock

**Problem:** `Scheduler.add_many` calls `add()` in a loop. Each `add()` acquires and releases
`self._lock` individually. A page with 50 discovered links = 50 serial lock cycles.

**Fix:** Inline the dedup + heap-push logic from `add()` into a single `async with self._lock:`
block inside `add_many`. The per-URL `add()` method remains unchanged for single-URL callers.

**Files:** `ergane/crawler/scheduler.py`

### 1c. SQLite cache — WAL mode + persistent connection

**Problem:** `_get_sync` and `_set_sync` each call `sqlite3.connect()`, paying connection
creation overhead on every cache hit.

**Fix:** Open one connection at `__init__`, enable WAL journal mode
(`PRAGMA journal_mode=WAL`) for better concurrent reads, and protect it with a
`threading.Lock` since `asyncio.to_thread` dispatches to a thread pool.

**Files:** `ergane/crawler/cache.py`

### 1d. Worker idle path — event-driven

**Problem:** When `get_nowait()` returns `None`, workers do `await asyncio.sleep(0.1)`.
All 10 workers sleep through burst moments when a page's 50 links land in the queue
simultaneously.

**Fix:** Expose `Scheduler.wait_not_empty() -> None` — a thin wrapper around the existing
private `_not_empty` event. Workers call `await asyncio.wait_for(scheduler.wait_not_empty(),
timeout=0.5)` instead of sleeping. They wake the instant a URL is queued.

**Files:** `ergane/crawler/scheduler.py`, `ergane/crawler/engine.py`

---

## Phase 2 — Event-Driven Engine Loop

Medium-risk, concentrated entirely in `_crawl_iter`. No changes to workers, scheduler,
pipeline, or public API.

### The problem

`_crawl_iter` polls unconditionally every 100ms:

```python
while not item_queue.empty():
    yield item_queue.get_nowait()   # only drains on wakeup
await asyncio.sleep(0.1)           # unconditional 100ms pause
```

Every extracted item sits in `item_queue` for up to 100ms. Average latency for `stream()`
callers is 50ms per item, purely artificial.

### The fix

Replace the polling sleep with a blocking `item_queue.get()` that times out:

```python
try:
    item = await asyncio.wait_for(item_queue.get(), timeout=0.1)
    yield item                      # delivered immediately on arrival
except asyncio.TimeoutError:
    pass                            # no item ready; loop back and re-check
```

The loop now blocks until an item arrives (sub-millisecond delivery). The 100ms timeout
fires only when the queue is genuinely empty, preserving the existing heartbeat semantics
for shutdown checks and checkpoint saves.

The `finally` block's drain (`while not item_queue.empty(): yield item_queue.get_nowait()`)
stays unchanged.

### Interaction with Phase 1d

Phase 1d makes workers event-driven on the input side (waiting for new URLs).
Phase 2 makes the engine event-driven on the output side (waiting for new items).
Together they eliminate both idle sleeps in the hot path.

**Files:** `ergane/crawler/engine.py`

---

## Phase 3 — Scale & DX

### 3a. Memory-bounded pipeline consolidation

**Problem:** Non-parquet `consolidate()` loads every batch file into a single in-memory
DataFrame before writing the final output.

**Fix:** Add `consolidate_batches(batch_files, output_path)` to each `BatchWriter` subclass
with format-specific strategies:

| Format | Strategy |
|--------|----------|
| JSONL | `shutil` byte-copy each batch into output. Zero DataFrame. |
| CSV | Byte-copy; strip header row from every batch after the first. |
| JSON | Stream: write `[`, iterate JSONL batch lines with commas, write `]`. Max one line in RAM. |
| SQLite | Each batch `INSERT`s directly into the final `.db`. `consolidate()` becomes no-op. |
| Excel | Accepted limitation — inherently in-memory. Document it. |

`Pipeline.consolidate()` delegates to the writer's `consolidate_batches()` instead of the
shared in-memory concat path.

**Files:** `ergane/crawler/pipeline.py`

### 3b. Per-domain rate limits

**Problem:** Single global `max_requests_per_second` applies equally to all domains. A crawl
mixing a fast internal API and a polite-crawl-required public site must use the slowest rate
for both.

**Fix:** Add `domain_rate_limits: dict[str, float] = {}` to `CrawlConfig`. In
`Fetcher._get_bucket()`, check `config.domain_rate_limits.get(domain)` before falling back
to the global rate. CLI gets `--domain-rate-limit domain:rate` (repeatable).

**Files:** `ergane/models/schemas.py`, `ergane/crawler/fetcher.py`, `ergane/main.py`

### 3c. MCP crawl progress reporting

**Problem:** The MCP `crawl` tool calls `crawler.run()` — LLM clients wait for the entire
crawl to complete before seeing any feedback.

**Fix:** Switch to `crawler.stream()` and call `ctx.report_progress(pages_crawled,
max_pages)` on each item. The progress infrastructure added in commit 427970d is already
in place. Final result structure is unchanged; no protocol changes needed.

**Files:** `ergane/mcp/tools.py`

### 3d. Benchmarks

A `benchmarks/` directory with a self-contained script that:
1. Starts a local `http.server` serving synthetic HTML pages with links
2. Runs a timed crawl against it
3. Prints pages/sec, items/sec, and peak memory

Runnable with `uv run python benchmarks/run.py`. Establishes a baseline to validate gains
from Phases 1 and 2 and guard against future regressions.

**Files:** `benchmarks/run.py`

---

## Scope explicitly out

- Distributed / Redis-backed scheduler
- HTTP/2 multiplexing tuning
- Playwright connection pooling (separate concern from JS rendering)
