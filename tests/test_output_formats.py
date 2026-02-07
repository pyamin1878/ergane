"""Tests for CSV, Excel, JSON, JSONL, and SQLite output formats."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from src.crawler import Pipeline
from src.models import CrawlConfig, ParsedItem


@pytest.fixture
def temp_csv_path(temp_output_dir: Path) -> Path:
    """Temporary CSV file path."""
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    return temp_output_dir / "test_output.csv"


@pytest.fixture
def temp_excel_path(temp_output_dir: Path) -> Path:
    """Temporary Excel file path."""
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    return temp_output_dir / "test_output.xlsx"


@pytest.fixture
def temp_json_path(temp_output_dir: Path) -> Path:
    """Temporary JSON file path."""
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    return temp_output_dir / "test_output.json"


@pytest.fixture
def temp_jsonl_path(temp_output_dir: Path) -> Path:
    """Temporary JSONL file path."""
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    return temp_output_dir / "test_output.jsonl"


@pytest.fixture
def temp_sqlite_path(temp_output_dir: Path) -> Path:
    """Temporary SQLite file path."""
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    return temp_output_dir / "test_output.sqlite"


def make_item(url: str, title: str = "Test") -> ParsedItem:
    """Helper to create test items."""
    return ParsedItem(
        url=url,
        title=title,
        text="Test content",
        links=["https://example.com/link1", "https://example.com/link2"],
        extracted_data={"key": "value"},
        crawled_at=datetime.now(timezone.utc),
    )


class TestFormatDetection:
    """Test automatic format detection from file extension."""

    def test_detect_parquet(self, config: CrawlConfig, temp_parquet_path: Path):
        """Test detection of .parquet extension."""
        pipeline = Pipeline(config, temp_parquet_path)
        assert pipeline.output_format == "parquet"

    def test_detect_csv(self, config: CrawlConfig, temp_csv_path: Path):
        """Test detection of .csv extension."""
        pipeline = Pipeline(config, temp_csv_path)
        assert pipeline.output_format == "csv"

    def test_detect_xlsx(self, config: CrawlConfig, temp_excel_path: Path):
        """Test detection of .xlsx extension."""
        pipeline = Pipeline(config, temp_excel_path)
        assert pipeline.output_format == "excel"

    def test_detect_xls(self, config: CrawlConfig, temp_output_dir: Path):
        """Test detection of .xls extension."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.xls"
        pipeline = Pipeline(config, path)
        assert pipeline.output_format == "excel"

    def test_detect_json(self, config: CrawlConfig, temp_json_path: Path):
        """Test detection of .json extension."""
        pipeline = Pipeline(config, temp_json_path)
        assert pipeline.output_format == "json"

    def test_detect_jsonl(self, config: CrawlConfig, temp_jsonl_path: Path):
        """Test detection of .jsonl extension."""
        pipeline = Pipeline(config, temp_jsonl_path)
        assert pipeline.output_format == "jsonl"

    def test_detect_ndjson(self, config: CrawlConfig, temp_output_dir: Path):
        """Test detection of .ndjson extension."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.ndjson"
        pipeline = Pipeline(config, path)
        assert pipeline.output_format == "jsonl"

    def test_detect_sqlite(self, config: CrawlConfig, temp_sqlite_path: Path):
        """Test detection of .sqlite extension."""
        pipeline = Pipeline(config, temp_sqlite_path)
        assert pipeline.output_format == "sqlite"

    def test_detect_db(self, config: CrawlConfig, temp_output_dir: Path):
        """Test detection of .db extension."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.db"
        pipeline = Pipeline(config, path)
        assert pipeline.output_format == "sqlite"

    def test_unknown_extension_defaults_to_parquet(
        self, config: CrawlConfig, temp_output_dir: Path
    ):
        """Test that unknown extensions default to parquet."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.unknown"
        pipeline = Pipeline(config, path)
        assert pipeline.output_format == "parquet"

    def test_explicit_format_overrides_detection(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test that explicit format overrides file extension."""
        pipeline = Pipeline(config, temp_parquet_path, output_format="csv")
        assert pipeline.output_format == "csv"


class TestCSVOutput:
    """Test CSV output functionality."""

    @pytest.mark.asyncio
    async def test_write_csv_basic(self, config: CrawlConfig, temp_csv_path: Path):
        """Test basic CSV writing."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_csv_path)

        await pipeline.add(make_item("https://example.com/1", "Test Title"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".csv"

    @pytest.mark.asyncio
    async def test_csv_data_integrity(self, config: CrawlConfig, temp_csv_path: Path):
        """Test that data is correctly written to CSV."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_csv_path)

        item = make_item("https://example.com/test", "My Title")
        item.text = "Some test content"

        await pipeline.add(item)
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_csv(batch_files[0])

        assert df[0, "url"] == "https://example.com/test"
        assert df[0, "title"] == "My Title"
        assert df[0, "text"] == "Some test content"

    @pytest.mark.asyncio
    async def test_csv_consolidation(self, config: CrawlConfig, temp_csv_path: Path):
        """Test consolidating multiple CSV batch files."""
        config.batch_size = 3
        pipeline = Pipeline(config, temp_csv_path)

        for i in range(9):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()

        # Should have 3 batch files
        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 3

        # Consolidate
        final_path = pipeline.consolidate()

        # Batch files should be gone
        assert len(pipeline.get_batch_files()) == 0

        # Final file should exist with all data
        assert final_path.exists()
        df = pl.read_csv(final_path)
        assert len(df) == 9


class TestExcelOutput:
    """Test Excel output functionality."""

    @pytest.mark.asyncio
    async def test_write_excel_basic(self, config: CrawlConfig, temp_excel_path: Path):
        """Test basic Excel writing."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_excel_path)

        await pipeline.add(make_item("https://example.com/1", "Test Title"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".xlsx"

    @pytest.mark.asyncio
    async def test_excel_data_integrity(
        self, config: CrawlConfig, temp_excel_path: Path
    ):
        """Test that data is correctly written to Excel."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_excel_path)

        item = make_item("https://example.com/test", "My Title")
        item.text = "Some test content"

        await pipeline.add(item)
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_excel(batch_files[0])

        assert df[0, "url"] == "https://example.com/test"
        assert df[0, "title"] == "My Title"
        assert df[0, "text"] == "Some test content"

    @pytest.mark.asyncio
    async def test_excel_consolidation(
        self, config: CrawlConfig, temp_excel_path: Path
    ):
        """Test consolidating multiple Excel batch files."""
        config.batch_size = 3
        pipeline = Pipeline(config, temp_excel_path)

        for i in range(9):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()

        # Should have 3 batch files
        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 3

        # Consolidate
        final_path = pipeline.consolidate()

        # Batch files should be gone
        assert len(pipeline.get_batch_files()) == 0

        # Final file should exist with all data
        assert final_path.exists()
        df = pl.read_excel(final_path)
        assert len(df) == 9


class TestJSONOutput:
    """Test JSON output functionality."""

    @pytest.mark.asyncio
    async def test_write_json_basic(self, config: CrawlConfig, temp_json_path: Path):
        """Test basic JSON writing — batch files should be .jsonl."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_json_path)

        await pipeline.add(make_item("https://example.com/1", "Test Title"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".jsonl"

    @pytest.mark.asyncio
    async def test_json_data_integrity(
        self, config: CrawlConfig, temp_json_path: Path
    ):
        """Test that data round-trips correctly through JSONL batch files."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_json_path)

        item = make_item("https://example.com/test", "My Title")
        item.text = "Some test content"

        await pipeline.add(item)
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_ndjson(batch_files[0])

        assert df[0, "url"] == "https://example.com/test"
        assert df[0, "title"] == "My Title"
        assert df[0, "text"] == "Some test content"

    @pytest.mark.asyncio
    async def test_json_consolidation(
        self, config: CrawlConfig, temp_json_path: Path
    ):
        """Test consolidating multiple batches into a single .json file."""
        config.batch_size = 3
        pipeline = Pipeline(config, temp_json_path)

        for i in range(9):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 3

        final_path = pipeline.consolidate()

        assert len(pipeline.get_batch_files()) == 0
        assert final_path.exists()
        assert final_path.suffix == ".json"

        # Verify it's a valid JSON array readable by Polars
        df = pl.read_json(final_path)
        assert len(df) == 9

        # Verify it's valid JSON via stdlib
        with open(final_path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 9


class TestJSONLOutput:
    """Test JSONL (newline-delimited JSON) output functionality."""

    @pytest.mark.asyncio
    async def test_write_jsonl_basic(self, config: CrawlConfig, temp_jsonl_path: Path):
        """Test basic JSONL writing — batch files should be .jsonl."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_jsonl_path)

        await pipeline.add(make_item("https://example.com/1", "Test Title"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".jsonl"

    @pytest.mark.asyncio
    async def test_jsonl_data_integrity(
        self, config: CrawlConfig, temp_jsonl_path: Path
    ):
        """Test that data round-trips correctly through JSONL files."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_jsonl_path)

        item = make_item("https://example.com/test", "My Title")
        item.text = "Some test content"

        await pipeline.add(item)
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_ndjson(batch_files[0])

        assert df[0, "url"] == "https://example.com/test"
        assert df[0, "title"] == "My Title"
        assert df[0, "text"] == "Some test content"

    @pytest.mark.asyncio
    async def test_jsonl_consolidation(
        self, config: CrawlConfig, temp_jsonl_path: Path
    ):
        """Test consolidating multiple batches into a single .jsonl file."""
        config.batch_size = 3
        pipeline = Pipeline(config, temp_jsonl_path)

        for i in range(9):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 3

        final_path = pipeline.consolidate()

        assert len(pipeline.get_batch_files()) == 0
        assert final_path.exists()
        assert final_path.suffix == ".jsonl"

        # Verify readable as NDJSON
        df = pl.read_ndjson(final_path)
        assert len(df) == 9

        # Verify each line is valid JSON
        with open(final_path) as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) == 9
        for line in lines:
            obj = json.loads(line)
            assert "url" in obj


class TestSQLiteOutput:
    """Test SQLite output functionality."""

    @pytest.mark.asyncio
    async def test_write_sqlite_basic(
        self, config: CrawlConfig, temp_sqlite_path: Path
    ):
        """Test basic SQLite writing — batch files should be .jsonl."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_sqlite_path)

        await pipeline.add(make_item("https://example.com/1", "Test Title"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".jsonl"

    @pytest.mark.asyncio
    async def test_sqlite_data_integrity(
        self, config: CrawlConfig, temp_sqlite_path: Path
    ):
        """Test that data is correctly written to SQLite after consolidation."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_sqlite_path)

        item = make_item("https://example.com/test", "My Title")
        item.text = "Some test content"

        await pipeline.add(item)
        await pipeline.flush()

        final_path = pipeline.consolidate()
        assert final_path.exists()

        # Query with sqlite3
        with sqlite3.connect(final_path) as conn:
            rows = conn.execute(
                f'SELECT url, title, text FROM "{final_path.stem}"'
            ).fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "https://example.com/test"
        assert rows[0][1] == "My Title"
        assert rows[0][2] == "Some test content"

    @pytest.mark.asyncio
    async def test_sqlite_consolidation(
        self, config: CrawlConfig, temp_sqlite_path: Path
    ):
        """Test consolidating multiple batches into a single .sqlite file."""
        config.batch_size = 3
        pipeline = Pipeline(config, temp_sqlite_path)

        for i in range(9):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 3

        final_path = pipeline.consolidate()

        assert len(pipeline.get_batch_files()) == 0
        assert final_path.exists()
        assert final_path.suffix == ".sqlite"

        # Query with sqlite3
        with sqlite3.connect(final_path) as conn:
            rows = conn.execute(
                f'SELECT * FROM "{final_path.stem}"'
            ).fetchall()

        assert len(rows) == 9


class TestExplicitFormat:
    """Test explicit format specification."""

    @pytest.mark.asyncio
    async def test_explicit_csv_format(
        self, config: CrawlConfig, temp_output_dir: Path
    ):
        """Test using explicit CSV format with .parquet extension."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.parquet"
        config.batch_size = 5

        pipeline = Pipeline(config, path, output_format="csv")

        await pipeline.add(make_item("https://example.com/1"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        # Batch files use the correct extension based on format
        assert batch_files[0].suffix == ".csv"

    @pytest.mark.asyncio
    async def test_explicit_excel_format(
        self, config: CrawlConfig, temp_output_dir: Path
    ):
        """Test using explicit Excel format."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.data"
        config.batch_size = 5

        pipeline = Pipeline(config, path, output_format="excel")

        await pipeline.add(make_item("https://example.com/1"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".xlsx"

    @pytest.mark.asyncio
    async def test_explicit_json_format(
        self, config: CrawlConfig, temp_output_dir: Path
    ):
        """Test using explicit JSON format with mismatched extension."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.parquet"
        config.batch_size = 5

        pipeline = Pipeline(config, path, output_format="json")

        await pipeline.add(make_item("https://example.com/1"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".jsonl"

    @pytest.mark.asyncio
    async def test_explicit_jsonl_format(
        self, config: CrawlConfig, temp_output_dir: Path
    ):
        """Test using explicit JSONL format with mismatched extension."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.csv"
        config.batch_size = 5

        pipeline = Pipeline(config, path, output_format="jsonl")

        await pipeline.add(make_item("https://example.com/1"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".jsonl"

    @pytest.mark.asyncio
    async def test_explicit_sqlite_format(
        self, config: CrawlConfig, temp_output_dir: Path
    ):
        """Test using explicit SQLite format with mismatched extension."""
        temp_output_dir.mkdir(parents=True, exist_ok=True)
        path = temp_output_dir / "test_output.csv"
        config.batch_size = 5

        pipeline = Pipeline(config, path, output_format="sqlite")

        await pipeline.add(make_item("https://example.com/1"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1
        assert batch_files[0].suffix == ".jsonl"
