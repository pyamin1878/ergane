import asyncio
import json
from pathlib import Path

import polars as pl

from src.models import CrawlConfig, ParsedItem


class Pipeline:
    """Data output pipeline with batched parquet writes."""

    def __init__(self, config: CrawlConfig, output_path: str | Path):
        self.config = config
        self.output_path = Path(output_path)
        self._buffer: list[ParsedItem] = []
        self._lock = asyncio.Lock()
        self._total_written = 0

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
        """Write buffer to parquet (must hold lock)."""
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

        if self.output_path.exists():
            existing = pl.read_parquet(self.output_path)
            df = pl.concat([existing, df])

        df.write_parquet(self.output_path)
        self._total_written += len(batch)

    async def flush(self) -> None:
        """Flush any remaining items in the buffer."""
        async with self._lock:
            while self._buffer:
                await self._flush_unlocked()
            if self._buffer:
                batch = self._buffer
                self._buffer = []

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

                if self.output_path.exists():
                    existing = pl.read_parquet(self.output_path)
                    df = pl.concat([existing, df])

                df.write_parquet(self.output_path)
                self._total_written += len(batch)

    @property
    def total_written(self) -> int:
        """Return total items written to output."""
        return self._total_written
