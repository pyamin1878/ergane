"""Tests for the data output pipeline."""
import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone

import polars as pl

from src.models import CrawlConfig, ParsedItem
from src.crawler import Pipeline


@pytest.fixture
def pipeline(config: CrawlConfig, temp_parquet_path: Path) -> Pipeline:
    """Create a pipeline instance for testing."""
    return Pipeline(config, temp_parquet_path)


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


class TestPipelineBasics:
    """Basic pipeline functionality tests."""

    @pytest.mark.asyncio
    async def test_add_single_item(self, pipeline: Pipeline):
        """Test adding a single item."""
        item = make_item("https://example.com/1")
        await pipeline.add(item)

        assert len(pipeline._buffer) == 1
        assert pipeline.total_written == 0

    @pytest.mark.asyncio
    async def test_flush_writes_data(self, pipeline: Pipeline, temp_parquet_path: Path):
        """Test that flush writes buffered data."""
        item = make_item("https://example.com/1")
        await pipeline.add(item)
        await pipeline.flush()

        assert pipeline.total_written == 1
        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1

    @pytest.mark.asyncio
    async def test_total_written_tracking(self, pipeline: Pipeline):
        """Test total written count."""
        for i in range(5):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()
        assert pipeline.total_written == 5


class TestBatchWriting:
    """Batch writing behavior tests."""

    @pytest.mark.asyncio
    async def test_auto_flush_at_batch_size(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test automatic flush when batch size is reached."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_parquet_path)

        # Add batch_size items
        for i in range(5):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        # Should have auto-flushed
        assert pipeline.total_written == 5
        assert len(pipeline._buffer) == 0

    @pytest.mark.asyncio
    async def test_partial_batch_requires_flush(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test that partial batches require explicit flush."""
        config.batch_size = 10
        pipeline = Pipeline(config, temp_parquet_path)

        for i in range(7):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        assert pipeline.total_written == 0
        assert len(pipeline._buffer) == 7

        await pipeline.flush()
        assert pipeline.total_written == 7

    @pytest.mark.asyncio
    async def test_multiple_batches(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test writing multiple batches."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_parquet_path)

        for i in range(12):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()

        # 2 full batches + 1 partial
        assert pipeline.total_written == 12
        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 3


class TestAddMany:
    """Bulk add functionality tests."""

    @pytest.mark.asyncio
    async def test_add_many_basic(self, pipeline: Pipeline):
        """Test adding multiple items at once."""
        items = [make_item(f"https://example.com/{i}") for i in range(5)]
        await pipeline.add_many(items)

        assert len(pipeline._buffer) == 5

    @pytest.mark.asyncio
    async def test_add_many_triggers_flush(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test add_many triggers flush when exceeding batch size."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_parquet_path)

        items = [make_item(f"https://example.com/{i}") for i in range(12)]
        await pipeline.add_many(items)

        assert pipeline.total_written == 10  # 2 full batches
        assert len(pipeline._buffer) == 2


class TestParquetOutput:
    """Parquet file output tests."""

    @pytest.mark.asyncio
    async def test_parquet_schema(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test that parquet has expected schema."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_parquet_path)

        await pipeline.add(make_item("https://example.com/1", "Test Title"))
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_parquet(batch_files[0])

        assert "url" in df.columns
        assert "title" in df.columns
        assert "text" in df.columns
        assert "links" in df.columns
        assert "extracted_data" in df.columns
        assert "crawled_at" in df.columns

    @pytest.mark.asyncio
    async def test_parquet_data_integrity(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test that data is correctly written to parquet."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_parquet_path)

        item = make_item("https://example.com/test", "My Title")
        item.text = "Some test content"
        item.links = ["https://link1.com", "https://link2.com"]
        item.extracted_data = {"custom": "data"}

        await pipeline.add(item)
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_parquet(batch_files[0])

        assert df[0, "url"] == "https://example.com/test"
        assert df[0, "title"] == "My Title"
        assert df[0, "text"] == "Some test content"
        assert json.loads(df[0, "links"]) == ["https://link1.com", "https://link2.com"]
        assert json.loads(df[0, "extracted_data"]) == {"custom": "data"}

    @pytest.mark.asyncio
    async def test_text_truncation(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test that long text is truncated to 10000 chars."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_parquet_path)

        item = make_item("https://example.com/long")
        item.text = "x" * 20000

        await pipeline.add(item)
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_parquet(batch_files[0])
        assert len(df[0, "text"]) == 10000

    @pytest.mark.asyncio
    async def test_null_text_handling(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test handling of null text."""
        config.batch_size = 5
        pipeline = Pipeline(config, temp_parquet_path)

        item = make_item("https://example.com/null")
        item.text = None

        await pipeline.add(item)
        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        df = pl.read_parquet(batch_files[0])
        assert df[0, "text"] is None


class TestConsolidation:
    """File consolidation tests."""

    @pytest.mark.asyncio
    async def test_consolidate_multiple_batches(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test consolidating multiple batch files."""
        config.batch_size = 3
        pipeline = Pipeline(config, temp_parquet_path)

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
        df = pl.read_parquet(final_path)
        assert len(df) == 9

    @pytest.mark.asyncio
    async def test_consolidate_single_batch(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test consolidating single batch file."""
        config.batch_size = 10
        pipeline = Pipeline(config, temp_parquet_path)

        for i in range(5):
            await pipeline.add(make_item(f"https://example.com/{i}"))

        await pipeline.flush()

        batch_files = pipeline.get_batch_files()
        assert len(batch_files) == 1

        final_path = pipeline.consolidate()

        assert final_path == temp_parquet_path
        df = pl.read_parquet(final_path)
        assert len(df) == 5

    @pytest.mark.asyncio
    async def test_consolidate_empty(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test consolidating when no batches exist."""
        pipeline = Pipeline(config, temp_parquet_path)
        final_path = pipeline.consolidate()
        assert final_path == temp_parquet_path


class TestConcurrency:
    """Concurrent access tests."""

    @pytest.mark.asyncio
    async def test_concurrent_adds(
        self, config: CrawlConfig, temp_parquet_path: Path
    ):
        """Test thread safety of concurrent adds."""
        config.batch_size = 100
        pipeline = Pipeline(config, temp_parquet_path)

        async def add_items(start: int, count: int):
            for i in range(count):
                await pipeline.add(make_item(f"https://example.com/{start + i}"))

        await asyncio.gather(
            add_items(0, 50),
            add_items(100, 50),
            add_items(200, 50),
        )

        await pipeline.flush()
        assert pipeline.total_written == 150
