"""Checkpoint save/load for resume functionality."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT_FILE = ".ergane_checkpoint.json"


@dataclass
class CrawlerCheckpoint:
    """Snapshot of crawler state for resuming interrupted jobs."""

    pages_crawled: int
    seen_urls: list[str]  # JSON-serializable
    pending_queue: list[dict]  # Serialized CrawlRequests
    batch_number: int
    timestamp: str


def save_checkpoint(path: Path, checkpoint: CrawlerCheckpoint) -> None:
    """Save checkpoint to JSON file.

    Args:
        path: File path for checkpoint.
        checkpoint: Crawler state to save.
    """
    with open(path, "w") as f:
        json.dump(asdict(checkpoint), f, indent=2)


def load_checkpoint(path: Path) -> CrawlerCheckpoint | None:
    """Load checkpoint from JSON file.

    Args:
        path: File path for checkpoint.

    Returns:
        CrawlerCheckpoint if file exists, None otherwise.
    """
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return CrawlerCheckpoint(**data)


def delete_checkpoint(path: Path) -> None:
    """Delete checkpoint file if it exists.

    Args:
        path: File path for checkpoint.
    """
    if path.exists():
        path.unlink()


def create_checkpoint(
    pages_crawled: int,
    seen_urls: set[str],
    pending_queue: list[tuple[int, int, dict]],
    batch_number: int,
) -> CrawlerCheckpoint:
    """Create a checkpoint from crawler state.

    Args:
        pages_crawled: Number of pages processed.
        seen_urls: Set of seen URL strings.
        pending_queue: List of (priority, counter, request_dict) tuples.
        batch_number: Current batch number.

    Returns:
        CrawlerCheckpoint instance.
    """
    return CrawlerCheckpoint(
        pages_crawled=pages_crawled,
        seen_urls=list(seen_urls),
        pending_queue=[
            {"priority": p, "counter": c, "request": r}
            for p, c, r in pending_queue
        ],
        batch_number=batch_number,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
