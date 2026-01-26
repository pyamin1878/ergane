import asyncio
import json
from pathlib import Path
from typing import Any, Literal, Type, TypeVar

import polars as pl
from pydantic import BaseModel

from src.models import CrawlConfig, ParsedItem
from src.schema import ParquetSchemaMapper

T = TypeVar("T", bound=BaseModel)

OutputFormat = Literal["parquet", "csv", "excel", "auto"]


class Pipeline:
    """Data output pipeline with batched writes supporting multiple formats.

    Uses incremental batch files to avoid O(n²) read-concat-rewrite pattern.
    Output files are named: base_000001.parquet, base_000001.csv, etc.
    Call consolidate() after crawl to merge into single file if desired.

    Supports two modes:
    1. Legacy mode (ParsedItem): Uses JSON strings for lists/dicts
    2. Schema mode (custom BaseModel): Uses native Polars types

    Supported output formats:
    - parquet: Efficient columnar storage (default)
    - csv: Universal text format, widely compatible
    - excel: .xlsx format for spreadsheet applications
    """

    EXTENSION_MAP = {
        ".parquet": "parquet",
        ".csv": "csv",
        ".xlsx": "excel",
        ".xls": "excel",
    }

    def __init__(
        self,
        config: CrawlConfig,
        output_path: str | Path,
        output_schema: Type[BaseModel] | None = None,
        output_format: OutputFormat = "auto",
    ):
        self.config = config
        self.output_path = Path(output_path)
        self.output_schema = output_schema
        self._buffer: list[BaseModel] = []
        self._lock = asyncio.Lock()
        self._total_written = 0
        self._batch_number = 0

        # Determine output format
        if output_format == "auto":
            self.output_format = self._detect_format(self.output_path)
        else:
            self.output_format = output_format

        # Create output directory if it doesn't exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def _detect_format(self, path: Path) -> str:
        """Detect output format from file extension."""
        suffix = path.suffix.lower()
        return self.EXTENSION_MAP.get(suffix, "parquet")

    def _get_batch_extension(self) -> str:
        """Get file extension for current output format."""
        format_extensions = {
            "parquet": ".parquet",
            "csv": ".csv",
            "excel": ".xlsx",
        }
        return format_extensions.get(self.output_format, ".parquet")

    def _get_batch_path(self) -> Path:
        """Generate path for next batch file."""
        stem = self.output_path.stem
        suffix = self._get_batch_extension()
        parent = self.output_path.parent
        return parent / f"{stem}_{self._batch_number:06d}{suffix}"

    async def add(self, item: BaseModel) -> None:
        """Add an item to the buffer, flushing if batch size reached."""
        async with self._lock:
            self._buffer.append(item)
            if len(self._buffer) >= self.config.batch_size:
                await self._flush_unlocked()

    async def add_many(self, items: list[BaseModel]) -> None:
        """Add multiple items to the buffer."""
        async with self._lock:
            self._buffer.extend(items)
            while len(self._buffer) >= self.config.batch_size:
                await self._flush_unlocked()

    async def _flush_unlocked(self) -> None:
        """Write buffer to batch file in configured format (must hold lock)."""
        if not self._buffer:
            return

        batch = self._buffer[: self.config.batch_size]
        self._buffer = self._buffer[self.config.batch_size :]

        # Use appropriate serialization based on schema mode
        if self.output_schema is not None:
            df = self._create_schema_dataframe(batch)
        else:
            df = self._create_legacy_dataframe(batch)

        # Write to numbered batch file (O(1) per batch instead of O(n))
        batch_path = self._get_batch_path()
        self._write_dataframe(df, batch_path)
        self._batch_number += 1
        self._total_written += len(batch)

    def _write_dataframe(self, df: pl.DataFrame, path: Path) -> None:
        """Write DataFrame to file in the configured format."""
        if self.output_format == "csv":
            self._write_csv(df, path)
        elif self.output_format == "excel":
            self._write_excel(df, path)
        else:
            df.write_parquet(path)

    def _write_csv(self, df: pl.DataFrame, path: Path) -> None:
        """Write DataFrame to CSV file."""
        df.write_csv(path)

    def _write_excel(self, df: pl.DataFrame, path: Path) -> None:
        """Write DataFrame to Excel file."""
        df.write_excel(path)

    def _create_legacy_dataframe(self, items: list[BaseModel]) -> pl.DataFrame:
        """Create DataFrame for legacy ParsedItem mode with JSON strings.

        Args:
            items: List of ParsedItem instances

        Returns:
            Polars DataFrame with JSON-serialized lists/dicts
        """
        records = []
        for item in items:
            if isinstance(item, ParsedItem):
                records.append({
                    "url": item.url,
                    "title": item.title,
                    "text": item.text[:10000] if item.text else None,
                    "links": json.dumps(item.links),
                    "extracted_data": json.dumps(item.extracted_data),
                    "crawled_at": item.crawled_at.isoformat(),
                })
            else:
                # Fallback for other BaseModel types in legacy mode
                records.append(item.model_dump())
        return pl.DataFrame(records)

    def _create_schema_dataframe(self, items: list[BaseModel]) -> pl.DataFrame:
        """Create DataFrame for custom schema mode with native types.

        Args:
            items: List of custom schema model instances

        Returns:
            Polars DataFrame with native Parquet types
        """
        return ParquetSchemaMapper.models_to_dataframe(items, self.output_schema)

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
        batch_ext = self._get_batch_extension()

        # Find all batch files
        batch_files = sorted(parent.glob(f"{stem}_*{batch_ext}"))

        if not batch_files:
            return self.output_path

        if len(batch_files) == 1:
            # Just rename the single batch file
            batch_files[0].rename(self.output_path)
            return self.output_path

        # Read and concatenate all batch files
        dfs = [self._read_batch_file(f) for f in batch_files]
        combined = pl.concat(dfs)
        self._write_dataframe(combined, self.output_path)

        # Clean up batch files
        for f in batch_files:
            f.unlink()

        return self.output_path

    def _read_batch_file(self, path: Path) -> pl.DataFrame:
        """Read a batch file in the appropriate format."""
        if self.output_format == "csv":
            return pl.read_csv(path)
        elif self.output_format == "excel":
            return pl.read_excel(path)
        else:
            return pl.read_parquet(path)

    def get_batch_files(self) -> list[Path]:
        """Return list of all batch files created."""
        stem = self.output_path.stem
        parent = self.output_path.parent
        batch_ext = self._get_batch_extension()
        return sorted(parent.glob(f"{stem}_*{batch_ext}"))

    @property
    def total_written(self) -> int:
        """Return total items written to output."""
        return self._total_written
