import asyncio
import json
import sqlite3
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, TypeVar

import polars as pl
from pydantic import BaseModel

from ergane.models import CrawlConfig, ParsedItem
from ergane.schema import ParquetSchemaMapper

T = TypeVar("T", bound=BaseModel)

OutputFormat = Literal["parquet", "csv", "excel", "json", "jsonl", "sqlite", "auto"]


# ---------------------------------------------------------------------------
# Per-format writer strategy classes
# ---------------------------------------------------------------------------


class BatchWriter(ABC):
    """Strategy interface for writing a batch of records to a file."""

    @property
    @abstractmethod
    def batch_extension(self) -> str:
        """File extension used for intermediate batch files."""

    @abstractmethod
    def write(self, df: pl.DataFrame, path: Path) -> None:
        """Write *df* to *path* (batch file)."""

    def write_final(self, df: pl.DataFrame, path: Path, stem: str) -> None:
        """Write the final consolidated output.

        Default implementation delegates to ``write()``.  Subclasses that
        use a different format for the final file (e.g. json vs jsonl) override
        this method.
        """
        self.write(df, path)

    def read_batch(self, path: Path) -> pl.DataFrame:
        """Read a previously written batch file back into a DataFrame."""
        return self._read(path)

    @abstractmethod
    def _read(self, path: Path) -> pl.DataFrame:
        """Format-specific read implementation."""


class ParquetWriter(BatchWriter):
    batch_extension = ".parquet"

    def write(self, df: pl.DataFrame, path: Path) -> None:
        df.write_parquet(path)

    def _read(self, path: Path) -> pl.DataFrame:
        return pl.read_parquet(path)


class CsvWriter(BatchWriter):
    batch_extension = ".csv"

    def write(self, df: pl.DataFrame, path: Path) -> None:
        df.write_csv(path)

    def _read(self, path: Path) -> pl.DataFrame:
        return pl.read_csv(path)


class ExcelWriter(BatchWriter):
    batch_extension = ".xlsx"

    def write(self, df: pl.DataFrame, path: Path) -> None:
        df.write_excel(path)

    def _read(self, path: Path) -> pl.DataFrame:
        return pl.read_excel(path)


class JsonlWriter(BatchWriter):
    """Batch writer that stores records as newline-delimited JSON.

    Both ``jsonl`` and ``json`` output formats use JSONL for intermediate batch
    files; only the *final* consolidated file differs (json = JSON array).
    ``sqlite`` also batches via JSONL before writing the final SQLite file.
    """

    batch_extension = ".jsonl"

    def write(self, df: pl.DataFrame, path: Path) -> None:
        df.write_ndjson(path)

    def _read(self, path: Path) -> pl.DataFrame:
        return pl.read_ndjson(path)


class JsonWriter(JsonlWriter):
    """Final output is a JSON array; batches are stored as JSONL."""

    def write_final(self, df: pl.DataFrame, path: Path, stem: str) -> None:
        df.write_json(path)


class SqliteWriter(JsonlWriter):
    """Final output is a SQLite database file; batches are stored as JSONL."""

    @staticmethod
    def _polars_to_sqlite_type(dtype: pl.DataType) -> str:
        integer_types = (
            pl.Int8, pl.Int16, pl.Int32, pl.Int64,
            pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
            pl.Boolean,
        )
        float_types = (pl.Float32, pl.Float64)
        if isinstance(dtype, integer_types):
            return "INTEGER"
        if isinstance(dtype, float_types):
            return "REAL"
        return "TEXT"

    def write_final(self, df: pl.DataFrame, path: Path, stem: str) -> None:
        table_name = stem
        rows = df.to_dicts()
        if not rows:
            return
        columns = df.columns
        col_defs = ", ".join(
            f'"{c}" {self._polars_to_sqlite_type(df[c].dtype)}' for c in columns
        )
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(f'"{c}"' for c in columns)
        with sqlite3.connect(path) as conn:
            conn.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')
            conn.executemany(
                f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
                [[row.get(c) for c in columns] for row in rows],
            )


# Map output format name → BatchWriter instance (singleton per format)
_WRITERS: dict[str, BatchWriter] = {
    "parquet": ParquetWriter(),
    "csv": CsvWriter(),
    "excel": ExcelWriter(),
    "json": JsonWriter(),
    "jsonl": JsonlWriter(),
    "sqlite": SqliteWriter(),
}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


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
    - json: JSON array format for APIs/web
    - jsonl: Newline-delimited JSON for streaming pipelines
    - sqlite: SQLite database for querying/sharing
    """

    EXTENSION_MAP = {
        ".parquet": "parquet",
        ".csv": "csv",
        ".xlsx": "excel",
        ".xls": "excel",
        ".json": "json",
        ".jsonl": "jsonl",
        ".ndjson": "jsonl",
        ".sqlite": "sqlite",
        ".db": "sqlite",
    }

    def __init__(
        self,
        config: CrawlConfig,
        output_path: str | Path,
        output_schema: type[BaseModel] | None = None,
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

        self._writer: BatchWriter = _WRITERS.get(
            self.output_format, _WRITERS["parquet"]
        )

        # Create output directory if it doesn't exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def _detect_format(self, path: Path) -> str:
        """Detect output format from file extension."""
        suffix = path.suffix.lower()
        return self.EXTENSION_MAP.get(suffix, "parquet")

    def _get_batch_path(self) -> Path:
        """Generate path for next batch file."""
        stem = self.output_path.stem
        suffix = self._writer.batch_extension
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

        batch_path = self._get_batch_path()
        self._writer.write(df, batch_path)
        self._batch_number += 1
        self._total_written += len(batch)

    def _create_legacy_dataframe(self, items: list[BaseModel]) -> pl.DataFrame:
        """Create DataFrame for legacy ParsedItem mode with JSON strings."""
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
                records.append(item.model_dump())
        return pl.DataFrame(records)

    def _create_schema_dataframe(self, items: list[BaseModel]) -> pl.DataFrame:
        """Create DataFrame for custom schema mode with native types."""
        df = ParquetSchemaMapper.models_to_dataframe(items, self.output_schema)
        # Apply the same 10,000-char cap as legacy mode to prevent unbounded
        # string fields from bloating the output on large crawls.
        str_cols = [col for col in df.columns if df[col].dtype == pl.Utf8]
        if str_cols:
            df = df.with_columns(
                [pl.col(col).str.slice(0, 10000) for col in str_cols]
            )
        return df

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
        batch_ext = self._writer.batch_extension

        # Find all batch files
        batch_files = sorted(parent.glob(f"{stem}_*{batch_ext}"))

        if not batch_files:
            return self.output_path

        if len(batch_files) == 1 and self.output_format not in ("json", "sqlite"):
            # Just rename the single batch file
            batch_files[0].rename(self.output_path)
            return self.output_path

        # Read and concatenate all batch files.
        # Parquet: use the lazy API so Polars scans files without loading all
        # DataFrames into RAM simultaneously.  Other formats fall back to an
        # incremental concat.
        if self.output_format == "parquet":
            combined = pl.scan_parquet(batch_files).collect()
        else:
            combined = pl.DataFrame()
            for f in batch_files:
                batch_df = self._writer.read_batch(f)
                if len(combined) > 0:
                    combined = pl.concat([combined, batch_df])
                else:
                    combined = batch_df

        # Deduplicate by URL, keeping the last occurrence
        if "url" in combined.columns:
            combined = combined.unique(subset=["url"], keep="last")

        # Write to a temp file first, then rename atomically
        suffix = self.output_path.suffix or ".tmp"
        with tempfile.NamedTemporaryFile(
            dir=parent, suffix=suffix, delete=False
        ) as tmp_f:
            tmp_path = Path(tmp_f.name)
        try:
            self._writer.write_final(combined, tmp_path, stem)
            tmp_path.replace(self.output_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        # Batch files are removed only after the final file is safely in place.
        for f in batch_files:
            f.unlink()

        return self.output_path

    def get_batch_files(self) -> list[Path]:
        """Return list of all batch files created."""
        stem = self.output_path.stem
        parent = self.output_path.parent
        batch_ext = self._writer.batch_extension
        return sorted(parent.glob(f"{stem}_*{batch_ext}"))

    @property
    def total_written(self) -> int:
        """Return total items written to output."""
        return self._total_written

    # ------------------------------------------------------------------
    # Legacy accessors kept for backward compatibility with existing tests
    # ------------------------------------------------------------------

    @staticmethod
    def _polars_to_sqlite_type(dtype: pl.DataType) -> str:
        return SqliteWriter._polars_to_sqlite_type(dtype)

    def _write_dataframe(self, df: pl.DataFrame, path: Path) -> None:
        self._writer.write(df, path)

    def _read_batch_file(self, path: Path) -> pl.DataFrame:
        return self._writer.read_batch(path)
