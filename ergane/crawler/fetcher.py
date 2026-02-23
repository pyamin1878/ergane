import asyncio
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ergane.crawler.cache import ResponseCache
from ergane.logging import get_logger
from ergane.models import CrawlConfig, CrawlRequest, CrawlResponse

_logger = get_logger()


class TokenBucket:
    """Token bucket rate limiter for per-domain throttling."""

    def __init__(self, rate: float, capacity: float | None = None):
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return

                wait_time = (1 - self.tokens) / self.rate

            # Sleep OUTSIDE the lock so other workers aren't blocked
            await asyncio.sleep(wait_time)


class Fetcher:
    """Async HTTP client with retry, rate limiting, and robots.txt support."""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._domain_buckets: dict[str, TokenBucket] = {}
        self._robots_cache: dict[str, RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()
        self.cache: ResponseCache | None = None
        if config.cache_enabled:
            self.cache = ResponseCache(config.cache_dir, config.cache_ttl)

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
            proxy=self.config.proxy,
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

    _ROBOTS_CACHE_MAX = 1000

    async def _get_robots(self, url: str) -> RobotFileParser | None:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        async with self._robots_lock:
            if robots_url in self._robots_cache:
                return self._robots_cache[robots_url]
            # Evict the single oldest entry (insertion-order) when the cache
            # is full.  Clearing all entries at once would cause a thundering
            # herd of simultaneous robots.txt re-fetches for every domain.
            if len(self._robots_cache) >= self._ROBOTS_CACHE_MAX:
                oldest_key = next(iter(self._robots_cache))
                del self._robots_cache[oldest_key]
                _logger.debug(
                    "robots.txt cache: evicted %s (limit=%d)",
                    oldest_key,
                    self._ROBOTS_CACHE_MAX,
                )

        try:
            assert self._client is not None, "Fetcher not initialized"
            resp = await self._client.get(
                robots_url, timeout=self.config.request_timeout
            )
            if resp.status_code == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                async with self._robots_lock:
                    self._robots_cache[robots_url] = rp
                return rp
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            _logger.debug("robots.txt fetch failed for %s: %s", robots_url, exc)

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

        # Check robots.txt BEFORE the cache so that updated disallow rules are
        # always respected even when a cached response exists for the URL.
        if not await self.can_fetch(request.url):
            return CrawlResponse(
                url=request.url,
                status_code=403,
                error="Blocked by robots.txt",
                request=request,
            )

        # Check cache after robots check
        if self.cache:
            cached = await self.cache.get(request.url)
            if cached:
                return CrawlResponse(
                    url=cached.url,
                    status_code=cached.status_code,
                    content=cached.content,
                    headers=cached.headers,
                    request=request,
                    from_cache=True,
                )

        domain = self._get_domain(request.url)
        bucket = self._get_bucket(domain)

        last_error: str | None = None
        for attempt in range(self.config.max_retries + 1):
            await bucket.acquire()

            try:
                extra_headers = request.metadata.get("headers", {})
                resp = await self._client.get(request.url, headers=extra_headers)
                response = CrawlResponse(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    content=resp.text if resp.status_code == 200 else "",
                    headers=dict(resp.headers),
                    request=request,
                )

                # Cache successful responses
                if self.cache and response.status_code == 200:
                    await self.cache.set(
                        response.url,
                        response.status_code,
                        response.content,
                        response.headers,
                    )

                return response
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
