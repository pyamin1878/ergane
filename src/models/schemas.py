from pydantic import BaseModel, Field, HttpUrl
from typing import Any
from datetime import datetime


class CrawlConfig(BaseModel):
    """Configuration for the crawler."""

    max_requests_per_second: float = Field(default=10.0, gt=0)
    max_concurrent_requests: int = Field(default=50, gt=0)
    request_timeout: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay: float = Field(default=1.0, gt=0)
    respect_robots_txt: bool = Field(default=True)
    user_agent: str = Field(
        default="FastCrawl/0.1 (+https://github.com/fastcrawl)"
    )
    max_queue_size: int = Field(default=10000, gt=0)
    batch_size: int = Field(default=100, gt=0)


class CrawlRequest(BaseModel):
    """A URL to be crawled with optional metadata."""

    url: str
    depth: int = Field(default=0, ge=0)
    priority: int = Field(default=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __lt__(self, other: "CrawlRequest") -> bool:
        return self.priority > other.priority


class CrawlResponse(BaseModel):
    """Response from fetching a URL."""

    url: str
    status_code: int
    content: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = None
    request: CrawlRequest


class ParsedItem(BaseModel):
    """Extracted data from a crawled page."""

    url: str
    title: str | None = None
    text: str | None = None
    links: list[str] = Field(default_factory=list)
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    crawled_at: datetime = Field(default_factory=datetime.utcnow)
