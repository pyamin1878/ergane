from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Type
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from ergane._version import __version__


def _default_user_agent() -> str:
    return f"Ergane/{__version__} (+https://github.com/pyamin1878/ergane)"


class CrawlConfig(BaseModel):
    """Configuration for the crawler."""

    max_requests_per_second: float = Field(default=10.0, gt=0)
    max_concurrent_requests: int = Field(default=10, gt=0)
    request_timeout: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay: float = Field(default=1.0, gt=0)
    respect_robots_txt: bool = Field(default=True)
    user_agent: str = Field(default_factory=_default_user_agent)
    max_queue_size: int = Field(default=10000, gt=0)
    batch_size: int = Field(default=100, gt=0)
    output_schema: Type[BaseModel] | None = Field(default=None)
    proxy: str | None = Field(default=None, description="HTTP/HTTPS proxy URL")

    # Caching
    cache_enabled: bool = Field(default=False)
    cache_dir: Path = Field(default=Path(".ergane_cache"))
    cache_ttl: int = Field(default=3600, description="Cache TTL in seconds")

    model_config = {"arbitrary_types_allowed": True}


class CrawlRequest(BaseModel):
    """A URL to be crawled with optional metadata."""

    url: str
    depth: int = Field(default=0, ge=0)
    priority: int = Field(default=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https scheme")
        if not parsed.netloc:
            raise ValueError("URL must have a valid host")
        return v

    def __lt__(self, other: "CrawlRequest") -> bool:
        return self.priority > other.priority


class CrawlResponse(BaseModel):
    """Response from fetching a URL."""

    url: str
    status_code: int
    content: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
    request: CrawlRequest
    from_cache: bool = False


class ParsedItem(BaseModel):
    """Extracted data from a crawled page."""

    url: str
    title: str | None = None
    text: str | None = None
    links: list[str] = Field(default_factory=list)
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    crawled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
