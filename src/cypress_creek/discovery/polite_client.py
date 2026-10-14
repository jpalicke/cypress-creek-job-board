# ABOUTME: One polite HTTP client for discovery: rate limit, refresh window, ETag cache, backoff.
# ABOUTME: Every request goes through the SSRF guarded transport. Failures are typed, never bodies.
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from cypress_creek.discovery.cache import CacheEntry, ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy, parse_retry_after
from cypress_creek.discovery.rate_limiter import Clock, HostRateLimiter
from cypress_creek.ingest.safe_http import FetchLimits, FetchResponse, fetch_url


class FetchFn(Protocol):
    def __call__(
        self,
        url: str,
        *,
        limits: FetchLimits,
        if_none_match: str | None,
        pass_through_statuses: bool,
    ) -> FetchResponse: ...


class PoliteFetchError(Exception):
    """A stable failure reason. Never carries the remote body or URL."""

    def __init__(self, reason_code: str) -> None:
        super().__init__("Resource could not be fetched politely")
        self.reason_code = reason_code


class RetriesExhausted(PoliteFetchError):
    def __init__(self, last_status: int) -> None:
        super().__init__("retries_exhausted")
        self.last_status = last_status


class NotFound(PoliteFetchError):
    def __init__(self) -> None:
        super().__init__("not_found")


class UnexpectedNotModified(PoliteFetchError):
    def __init__(self) -> None:
        super().__init__("unexpected_not_modified")


@dataclass(frozen=True)
class CachedResponse:
    url: str
    body: bytes
    etag: str | None
    fetched_at: float
    from_cache: bool
    status: int


class PoliteClient:
    def __init__(
        self,
        policy: FetchPolicy,
        cache: ResponseCache,
        limiter: HostRateLimiter,
        clock: Clock,
        *,
        limits: FetchLimits,
        fetch: FetchFn = fetch_url,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._policy = policy
        self._cache = cache
        self._limiter = limiter
        self._clock = clock
        self._limits = limits
        self._fetch = fetch
        self._random_source = random_source

    def get(self, url: str) -> CachedResponse:
        """The body for url: from the cache inside the refresh window, else fetched politely."""
        cached = self._cache.get(url)
        if cached is not None and self._is_fresh(cached):
            return _from_entry(url, cached, status=200)
        response = self._fetch_with_retries(url, cached.etag if cached else None)
        if response.status == 404:
            raise NotFound()
        now = self._clock.time()
        if response.status == 304:
            if cached is None:
                raise UnexpectedNotModified()
            self._cache.put(url, cached.body, cached.etag, now)
            return CachedResponse(url, cached.body, cached.etag, now, True, 304)
        self._cache.put(url, response.body, response.etag, now)
        return CachedResponse(url, response.body, response.etag, now, False, response.status)

    def _fetch_with_retries(self, url: str, etag: str | None) -> FetchResponse:
        host = urlsplit(url).hostname or ""
        for attempt in range(self._policy.max_retries + 1):
            self._limiter.wait(host)
            try:
                response = self._fetch(
                    url, limits=self._limits, if_none_match=etag, pass_through_statuses=True
                )
            finally:
                self._limiter.finished(host)
            if not _is_retryable(response.status):
                return response
            if attempt == self._policy.max_retries:
                raise RetriesExhausted(response.status)
            retry_after = parse_retry_after(
                response.retry_after, datetime.fromtimestamp(self._clock.time(), UTC)
            )
            self._clock.sleep(
                self._policy.backoff_delay(attempt, retry_after, self._random_source())
            )
        raise AssertionError("unreachable: the final attempt returns or raises")

    def _is_fresh(self, entry: CacheEntry) -> bool:
        age = self._clock.time() - entry.fetched_at
        return 0 <= age < self._policy.refresh_interval_seconds


def _is_retryable(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def _from_entry(url: str, entry: CacheEntry, *, status: int) -> CachedResponse:
    return CachedResponse(url, entry.body, entry.etag, entry.fetched_at, True, status)
