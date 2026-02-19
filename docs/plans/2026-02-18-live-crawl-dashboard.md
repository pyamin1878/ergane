# Live Crawl Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the minimal progress bar with a two-row Rich Live dashboard showing real-time throughput and health stats during a crawl.

**Architecture:** `Crawler` gains a `_stats` dict updated by each worker under the existing `_counter_lock`, and a `stats` property that returns a snapshot with derived metrics. The CLI replaces `with progress:` with `rich.live.Live`, driven by a `_make_renderable()` helper that reads `crawler.stats` each frame.

**Tech Stack:** Python 3.10+, `rich` (already a dependency — `Live`, `Group`, `Table`, `MofNCompleteColumn`, `TimeRemainingColumn`), `pytest-asyncio` (existing test infra).

---

## Task 1: Write the failing test for `crawler.stats`

**Files:**
- Modify: `tests/test_engine.py`

**Step 1: Add the failing test**

Open `tests/test_engine.py`. Find the `TestCrawlerContextManager` class (around line 38).
Add this test at the end of that class:

```python
@pytest.mark.asyncio
async def test_stats_after_crawl(self, engine_server: str):
    """stats property returns correct counters after a crawl."""
    async with Crawler(
        urls=[f"{engine_server}/"],
        max_pages=5,
        max_depth=1,
        rate_limit=100.0,
        respect_robots_txt=False,
    ) as c:
        await c.run()

    stats = c.stats
    assert set(stats.keys()) == {
        "pages_crawled",
        "items_extracted",
        "errors",
        "cache_hits",
        "pages_per_sec",
        "elapsed",
    }
    assert stats["pages_crawled"] == 2
    assert stats["items_extracted"] == 2
    assert stats["errors"] == 0
    assert stats["cache_hits"] == 0
    assert stats["elapsed"] > 0
    assert stats["pages_per_sec"] >= 0
```

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_engine.py::TestCrawlerContextManager::test_stats_after_crawl -v
```

Expected: `FAILED` — `AttributeError: 'Crawler' object has no attribute 'stats'`

---

## Task 2: Add `_stats` and `_start_time` to `Crawler.__init__`

**Files:**
- Modify: `ergane/crawler/engine.py`

**Step 1: Add fields in `__init__`**

In `Crawler.__init__`, find the line:

```python
        self._fetcher: Fetcher | None = None
        self._owns_fetcher = False
```

Add these lines immediately before it:

```python
        self._stats: dict[str, int] = {
            "pages_crawled": 0,
            "items_extracted": 0,
            "errors": 0,
            "cache_hits": 0,
        }
        self._start_time: float = 0.0

```

**Step 2: Add `stats` property**

Find the `pages_crawled` property:

```python
    @property
    def pages_crawled(self) -> int:
        return self._pages_crawled
```

Add the `stats` property immediately after it:

```python
    @property
    def stats(self) -> dict:
        """Return a snapshot of crawl statistics.

        Keys: pages_crawled, items_extracted, errors, cache_hits,
              pages_per_sec (derived), elapsed (derived, seconds).
        """
        import time

        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
        return {
            **self._stats,
            "elapsed": elapsed,
            "pages_per_sec": self._stats["pages_crawled"] / max(elapsed, 0.1),
        }
```

**Step 3: Run the test — expect it still fails** (counters are all zero)

```bash
uv run pytest tests/test_engine.py::TestCrawlerContextManager::test_stats_after_crawl -v
```

Expected: `FAILED` — `AssertionError: assert 0 == 2` (pages_crawled is 0)

---

## Task 3: Set `_start_time` and update counters in `_crawl_iter` / `_worker`

**Files:**
- Modify: `ergane/crawler/engine.py`

**Step 1: Set `_start_time` at the start of `_crawl_iter`**

In `_crawl_iter`, find the first line after the docstring:

```python
        # Resolve allowed domains from seed URLs
        for url in self._start_urls:
```

Add one line before it:

```python
        import time
        self._start_time = time.monotonic()

```

**Step 2: Track `errors` in `_worker`**

In `_worker`, find:

```python
                if response.error:
                    _logger.warning(
                        "Fetch error for %s: %s",
                        request.url, response.error,
                    )
```

Replace with:

```python
                if response.error:
                    _logger.warning(
                        "Fetch error for %s: %s",
                        request.url, response.error,
                    )
                    async with self._counter_lock:
                        self._stats["errors"] += 1
```

**Step 3: Track `cache_hits` in `_worker`**

In `_worker`, find:

```python
                # Apply response hooks
                hooked_response = await self._apply_response_hooks(
```

Add before it:

```python
                if response.from_cache:
                    async with self._counter_lock:
                        self._stats["cache_hits"] += 1

```

**Step 4: Track `pages_crawled` and `items_extracted` in `_worker`**

Find the existing `pages_crawled` increment:

```python
                async with self._counter_lock:
                    self._pages_crawled += 1
```

Replace with:

```python
                async with self._counter_lock:
                    self._pages_crawled += 1
                    self._stats["pages_crawled"] += 1
```

Then find where items are sent to the queue:

```python
                    # Send to pipeline and stream queue
                    if pipeline is not None:
                        await pipeline.add(item)
                    await item_queue.put(item)
```

Replace with:

```python
                    # Send to pipeline and stream queue
                    if pipeline is not None:
                        await pipeline.add(item)
                    await item_queue.put(item)
                    async with self._counter_lock:
                        self._stats["items_extracted"] += 1
```

**Step 5: Run the test — expect it to pass**

```bash
uv run pytest tests/test_engine.py::TestCrawlerContextManager::test_stats_after_crawl -v
```

Expected: `PASSED`

**Step 6: Run the full test suite to confirm no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

**Step 7: Commit**

```bash
git add ergane/crawler/engine.py tests/test_engine.py
git commit -m "feat(engine): add crawler.stats property with live counters"
```

---

## Task 4: Update imports in `main.py`

**Files:**
- Modify: `ergane/main.py`

**Step 1: Replace the `rich.progress` import block**

Find the existing import:

```python
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
```

Replace with:

```python
import datetime

from rich.console import Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table
```

**Step 2: No test needed** — this is a pure import change; the next task wires it up.

---

## Task 5: Add `_make_renderable` helper and replace the progress block

**Files:**
- Modify: `ergane/main.py`

**Step 1: Add `_make_renderable` helper**

Find the `print_presets_table` function (near the top of the file, after imports).
Add this function immediately before it:

```python
def _make_renderable(crawler, progress, task_id: int) -> Group:
    """Build the Rich Live renderable from current crawler stats."""
    stats = crawler.stats
    progress.update(task_id, completed=stats["pages_crawled"])

    elapsed = stats["elapsed"]
    elapsed_str = str(datetime.timedelta(seconds=int(elapsed)))
    speed_str = f"{stats['pages_per_sec']:.1f} p/s"

    table = Table(box=None, padding=(0, 2), show_header=True, header_style="bold")
    table.add_column("Extracted", style="green", justify="right")
    table.add_column("Errors", style="red", justify="right")
    table.add_column("Cache hits", style="cyan", justify="right")
    table.add_column("Elapsed", justify="right")
    table.add_column("Speed", justify="right")
    table.add_row(
        str(stats["items_extracted"]),
        str(stats["errors"]),
        str(stats["cache_hits"]),
        elapsed_str,
        speed_str,
    )

    return Group(progress, table)

```

**Step 2: Replace the `_run_with_progress` progress block**

Find the existing `_run_with_progress` inner function in the `crawl` command. It currently looks like:

```python
    async def _run_with_progress():
        async with crawler:
            if no_progress:
                await crawler.run()
            else:
                progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    TextColumn("[cyan]{task.fields[url]}"),
                )
                with progress:
                    task = progress.add_task(
                        "Crawling", total=effective_max_pages, url=""
                    )
                    async for item in crawler.stream():
                        truncated_url = getattr(item, "url", "")
                        if len(truncated_url) > 50:
                            truncated_url = truncated_url[:50] + "..."
                        progress.update(task, advance=1, url=truncated_url)
```

Replace the entire `_run_with_progress` function with:

```python
    async def _run_with_progress():
        async with crawler:
            if no_progress:
                await crawler.run()
            else:
                progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TimeRemainingColumn(),
                )
                task_id = progress.add_task("Crawling", total=effective_max_pages)

                with Live(
                    _make_renderable(crawler, progress, task_id),
                    refresh_per_second=4,
                    transient=False,
                ) as live:
                    async for item in crawler.stream():
                        live.update(_make_renderable(crawler, progress, task_id))
```

**Step 3: Smoke test the CLI**

Run a short preset crawl and observe the Live dashboard in the terminal:

```bash
uv run ergane crawl --preset quotes -o /tmp/quotes.csv -n 5
```

Expected: a two-row display — progress bar on top, stats table (Extracted / Errors / Cache hits / Elapsed / Speed) below. No scrambled output. Final frame stays visible after crawl completes.

**Step 4: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass (CLI changes are not unit-tested, but existing tests exercise the engine).

**Step 5: Commit**

```bash
git add ergane/main.py
git commit -m "feat(cli): replace progress bar with Rich Live dashboard"
```

---

## Task 6: Final check and lint

**Step 1: Run linter**

```bash
uv run ruff check ergane/crawler/engine.py ergane/main.py
```

Expected: no errors. If `import time` inside `stats` property or `_crawl_iter` triggers a lint warning, move those imports to the top of the file.

**Step 2: Fix any lint issues, then commit if needed**

```bash
git add ergane/crawler/engine.py ergane/main.py
git commit -m "fix(lint): move stdlib imports to top of module"
```

Only create this commit if there were lint fixes. Skip otherwise.

---

## Done

The dashboard shows:
- **Top row:** spinner, "Crawling", bar, `M/N pages`, time remaining
- **Bottom row:** items extracted, errors, cache hits, elapsed, speed (p/s)

`crawler.stats` is also available to programmatic API users at any point during a crawl.
