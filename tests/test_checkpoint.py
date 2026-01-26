"""Tests for checkpoint save/load functionality."""

import json
from pathlib import Path

import pytest

from src.crawler.checkpoint import (
    CrawlerCheckpoint,
    create_checkpoint,
    delete_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


@pytest.fixture
def checkpoint_path(tmp_path: Path) -> Path:
    """Fixture for temporary checkpoint file path."""
    return tmp_path / "test_checkpoint.json"


@pytest.fixture
def sample_checkpoint() -> CrawlerCheckpoint:
    """Fixture for a sample checkpoint."""
    return CrawlerCheckpoint(
        pages_crawled=50,
        seen_urls=["https://example.com/page1", "https://example.com/page2"],
        pending_queue=[
            {
                "priority": -1,
                "counter": 1,
                "request": {
                    "url": "https://example.com/page3",
                    "depth": 1,
                    "priority": 0,
                    "metadata": {},
                },
            }
        ],
        batch_number=2,
        timestamp="2026-01-26T12:00:00+00:00",
    )


def test_save_checkpoint(checkpoint_path: Path, sample_checkpoint: CrawlerCheckpoint):
    """Test saving a checkpoint to file."""
    save_checkpoint(checkpoint_path, sample_checkpoint)

    assert checkpoint_path.exists()
    with open(checkpoint_path) as f:
        data = json.load(f)

    assert data["pages_crawled"] == 50
    assert len(data["seen_urls"]) == 2
    assert len(data["pending_queue"]) == 1
    assert data["batch_number"] == 2


def test_load_checkpoint(checkpoint_path: Path, sample_checkpoint: CrawlerCheckpoint):
    """Test loading a checkpoint from file."""
    save_checkpoint(checkpoint_path, sample_checkpoint)
    loaded = load_checkpoint(checkpoint_path)

    assert loaded is not None
    assert loaded.pages_crawled == sample_checkpoint.pages_crawled
    assert loaded.seen_urls == sample_checkpoint.seen_urls
    assert loaded.batch_number == sample_checkpoint.batch_number


def test_load_checkpoint_nonexistent(checkpoint_path: Path):
    """Test loading from a nonexistent file returns None."""
    result = load_checkpoint(checkpoint_path)
    assert result is None


def test_delete_checkpoint(checkpoint_path: Path, sample_checkpoint: CrawlerCheckpoint):
    """Test deleting a checkpoint file."""
    save_checkpoint(checkpoint_path, sample_checkpoint)
    assert checkpoint_path.exists()

    delete_checkpoint(checkpoint_path)
    assert not checkpoint_path.exists()


def test_delete_checkpoint_nonexistent(checkpoint_path: Path):
    """Test deleting a nonexistent file does not raise."""
    delete_checkpoint(checkpoint_path)  # Should not raise


def test_create_checkpoint():
    """Test creating a checkpoint from crawler state."""
    seen = {"https://example.com/a", "https://example.com/b"}
    queue = [
        (
            -1,
            1,
            {"url": "https://example.com/c", "depth": 1, "priority": 0, "metadata": {}},
        )
    ]

    checkpoint = create_checkpoint(
        pages_crawled=10,
        seen_urls=seen,
        pending_queue=queue,
        batch_number=1,
    )

    assert checkpoint.pages_crawled == 10
    assert set(checkpoint.seen_urls) == seen
    assert len(checkpoint.pending_queue) == 1
    assert checkpoint.batch_number == 1
    assert checkpoint.timestamp  # Should have a timestamp
