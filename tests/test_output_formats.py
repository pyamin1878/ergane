"""Tests for CSV and Excel output formats."""

import json
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
