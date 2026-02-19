# Live Crawl Dashboard — Design

**Date:** 2026-02-18
**Status:** Approved
**Scope:** Terminal UX improvement — live stats panel during crawl

---

## Problem

The current terminal experience during a crawl is minimal:

- A single Rich progress bar showing a spinner, bar, percentage, and current URL
- Plain `logging` output written to stderr alongside the bar
- No throughput stats (pages/sec, ETA)
- No health/error visibility (error count, cache hits, items extracted vs pages visited)

Users have no feedback on whether the crawl is healthy or how long it will take.

---

## Goal

Replace the progress bar with a two-row Rich Live dashboard showing both
throughput and health metrics in real time, without changing any public API.

---

## Architecture

Two files change; nothing else is touched.

### `ergane/crawler/engine.py`

`Crawler` gains:

- `_stats: dict` — four integer counters initialized in `__init__`
- `_start_time: float` — set at the top of `_crawl_iter`
- `stats` property — returns a snapshot dict with the four raw counters plus
  two derived values (`pages_per_sec`, `elapsed`) computed on read
- Counter updates inside `_worker`, protected by the existing `_counter_lock`

### `ergane/main.py`

The `with progress:` block inside `_run_with_progress` is replaced with:

- A `_make_renderable(crawler, progress, task_id)` helper that reads
  `crawler.stats` and returns a `rich.console.Group`
- A `rich.live.Live` context manager that calls `live.update(_make_renderable(...))`
  on each yielded item, and lets Rich redraw at 4 fps

---

## Components

### `Crawler._stats` (engine.py)

```python
self._stats: dict[str, int] = {
    "pages_crawled": 0,
    "items_extracted": 0,
    "errors": 0,
    "cache_hits": 0,
}
self._start_time: float = 0.0
```

Updated under `_counter_lock` in `_worker`:

| Event | Counter |
|---|---|
| Page fetched successfully | `pages_crawled` |
| Item yielded from parser | `items_extracted` |
| `response.error` is truthy | `errors` |
| `X-Cache: HIT` in response headers | `cache_hits` |

### `Crawler.stats` property (engine.py)

Returns a plain dict (snapshot, not a reference):

```python
{
    "pages_crawled": int,
    "items_extracted": int,
    "errors": int,
    "cache_hits": int,
    "pages_per_sec": float,   # derived: pages_crawled / max(elapsed, 0.1)
    "elapsed": float,         # derived: time.monotonic() - _start_time
}
```

### `_make_renderable` (main.py)

Builds a `rich.console.Group` of:

1. **Progress bar** — spinner, label with `pages_per_sec` appended, bar,
   `MofNCompleteColumn`, `TimeRemainingColumn`
2. **Stats table** — one-row `rich.table.Table`:

```
 Extracted   Errors   Cache hits   Elapsed    Speed
 ─────────   ──────   ──────────   ───────    ─────
    142          3        28        0:01:14   3.2/s
```

### Live panel (main.py)

```python
with Live(_make_renderable(...), refresh_per_second=4, transient=False) as live:
    async for item in crawler.stream():
        stats = crawler.stats
        progress.update(task_id, completed=stats["pages_crawled"])
        live.update(_make_renderable(crawler, progress, task_id))
```

`transient=False` keeps the final frame visible after the crawl completes.

---

## Data Flow

```
_worker (engine.py)
  ├── fetch page → pages_crawled += 1
  ├── response.error → errors += 1
  ├── X-Cache: HIT → cache_hits += 1
  └── yield item → items_extracted += 1

crawler.stream() yields item
  └── CLI loop
        ├── progress.update(completed=pages_crawled)
        └── live.update(_make_renderable(crawler, progress, task_id))
              └── reads crawler.stats snapshot
                    └── builds Progress + Table → Group → Rich redraws
```

---

## Error Handling

| Scenario | Handling |
|---|---|
| `elapsed < 0.1s` at startup | `pages_per_sec` clamped: `pages_crawled / max(elapsed, 0.1)` |
| `--no-progress` flag | Unchanged code path; `_stats` still populates (useful for programmatic callers) |
| Ctrl-C / graceful shutdown | `Live` context manager exits cleanly; final stats frame remains visible |
| `_start_time` not yet set | Initialized to `0.0`; `elapsed` will be large but `pages_per_sec` will be near 0 |

---

## Testing

One new test in `tests/test_engine.py`:

- Run a short mock crawl (using the existing `respx`/`httpx` mock pattern)
- Assert `crawler.stats` returns a dict with all six expected keys
- Assert `pages_crawled > 0`, `elapsed > 0`, `pages_per_sec >= 0`
- Assert `errors >= 0` and `items_extracted >= 0`

No test for the Rich rendering — it is pure presentation with no logic to verify.

---

## Out of Scope

- Rich-formatted log output (`RichHandler`) — separate concern, separate PR
- End-of-crawl summary panel — can be added later on top of this
- Programmatic stats callbacks/events — `crawler.stats` property is sufficient
