import asyncio
import json
from pathlib import Path

import polars as pl

from src.models import CrawlConfig, ParsedItem


class Pipeline:
    """Data output pipeline with batched parquet writes.

    Uses incremental batch files to avoid O(n²) read-concat-rewrite pattern.
    Output files are named: base_000001.parquet, base_000002.parquet, etc.
    Call consolidate() after crawl to merge into single file if desired.
    """

    def __init__(self, config: CrawlConfig, output_path: str | Path):
        self.config = config
        self.output_path = Path(output_path)
        self._buffer: list[ParsedItem] = []
        self._lock = asyncio.Lock()
        self._total_written = 0
        self._batch_number = 0

        # Create output directory if it doesn't exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_batch_path(self) -> Path:
        """Generate path for next batch file."""
        stem = self.output_path.stem
        suffix = self.output_path.suffix or ".parquet"
        parent = self.output_path.parent
        return parent / f"{stem}_{self._batch_number:06d}{suffix}"

    async def add(self, item: ParsedItem) -> None:
        """Add an item to the buffer, flushing if batch size reached."""
        async with self._lock:
            self._buffer.append(item)
            if len(self._buffer) >= self.config.batch_size:
                await self._flush_unlocked()

    async def add_many(self, items: list[ParsedItem]) -> None:
        """Add multiple items to the buffer."""
        async with self._lock:
            self._buffer.extend(items)
            while len(self._buffer) >= self.config.batch_size:
                await self._flush_unlocked()

    async def _flush_unlocked(self) -> None:
        """Write buffer to parquet batch file (must hold lock)."""
        if not self._buffer:
            return

        batch = self._buffer[: self.config.batch_size]
        self._buffer = self._buffer[self.config.batch_size :]

        records = [
            {
                "url": item.url,
                "title": item.title,
                "text": item.text[:10000] if item.text else None,
                "links": json.dumps(item.links),
                "extracted_data": json.dumps(item.extracted_data),
                "crawled_at": item.crawled_at.isoformat(),
            }
            for item in batch
        ]

        df = pl.DataFrame(records)

        # Write to numbered batch file (O(1) per batch instead of O(n))
        batch_path = self._get_batch_path()
        df.write_parquet(batch_path)
        self._batch_number += 1
        self._total_written += len(batch)

    async def flush(self) -> None:
        """Flush any remaining items in the buffer."""
        async with self._lock:
            while self._buffer:
                await self._flush_unlocked()

    def consolidate(self) -> Path:
        """Merge all batch files into a single output file.

        Call this after crawl completes if you want a single file.
        Returns the path to the consolidated file.
        """
        stem = self.output_path.stem
        parent = self.output_path.parent

        # Find all batch files
        batch_files = sorted(parent.glob(f"{stem}_*.parquet"))

        if not batch_files:
            return self.output_path

        if len(batch_files) == 1:
            # Just rename the single batch file
            batch_files[0].rename(self.output_path)
            return self.output_path

        # Read and concatenate all batch files
        dfs = [pl.read_parquet(f) for f in batch_files]
        combined = pl.concat(dfs)
        combined.write_parquet(self.output_path)

        # Clean up batch files
        for f in batch_files:
            f.unlink()

        return self.output_path

    def get_batch_files(self) -> list[Path]:
        """Return list of all batch files created."""
        stem = self.output_path.stem
        parent = self.output_path.parent
        return sorted(parent.glob(f"{stem}_*.parquet"))

    @property
    def total_written(self) -> int:
        """Return total items written to output."""
        return self._total_written
