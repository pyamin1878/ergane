import asyncio
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from src.models import CrawlConfig, CrawlRequest, CrawlResponse


class TokenBucket:
    """Token bucket rate limiter for per-domain throttling."""

    def __init__(self, rate: float, capacity: float | None = None):
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class Fetcher:
    """Async HTTP client with retry, rate limiting, and robots.txt support."""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._domain_buckets: dict[str, TokenBucket] = {}
        self._robots_cache: dict[str, RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()

    async def __aenter__(self) -> "Fetcher":
        limits = httpx.Limits(
            max_connections=100,
            max_keepalive_connections=50,
        )
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(self.config.request_timeout),
            follow_redirects=True,
            headers={"User-Agent": self.config.user_agent},
            limits=limits,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    def _get_domain(self, url: str) -> str:
        return urlparse(url).netloc

    def _get_bucket(self, domain: str) -> TokenBucket:
        if domain not in self._domain_buckets:
            self._domain_buckets[domain] = TokenBucket(
                self.config.max_requests_per_second
            )
        return self._domain_buckets[domain]

    async def _get_robots(self, url: str) -> RobotFileParser | None:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        async with self._robots_lock:
            if robots_url in self._robots_cache:
                return self._robots_cache[robots_url]

        try:
            resp = await self._client.get(robots_url, timeout=10.0)
            if resp.status_code == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                async with self._robots_lock:
                    self._robots_cache[robots_url] = rp
                return rp
        except (httpx.HTTPError, httpx.TimeoutException):
            pass  # robots.txt fetch failed, allow crawl

        async with self._robots_lock:
            self._robots_cache[robots_url] = None
        return None

    async def can_fetch(self, url: str) -> bool:
        if not self.config.respect_robots_txt:
            return True

        robots = await self._get_robots(url)
        if robots is None:
            return True

        return robots.can_fetch(self.config.user_agent, url)

    async def fetch(self, request: CrawlRequest) -> CrawlResponse:
        if not self._client:
            raise RuntimeError("Fetcher not initialized. Use async with.")

        domain = self._get_domain(request.url)
        bucket = self._get_bucket(domain)

        if not await self.can_fetch(request.url):
            return CrawlResponse(
                url=request.url,
                status_code=403,
                error="Blocked by robots.txt",
                request=request,
            )

        last_error: str | None = None
        for attempt in range(self.config.max_retries + 1):
            await bucket.acquire()

            try:
                resp = await self._client.get(request.url)
                return CrawlResponse(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    content=resp.text if resp.status_code == 200 else "",
                    headers=dict(resp.headers),
                    request=request,
                )
            except httpx.TimeoutException:
                last_error = "Request timeout"
            except httpx.HTTPError as e:
                last_error = str(e)

            if attempt < self.config.max_retries:
                delay = self.config.retry_base_delay * (2**attempt)
                await asyncio.sleep(delay)

        return CrawlResponse(
            url=request.url,
            status_code=0,
            error=last_error,
            request=request,
        )
