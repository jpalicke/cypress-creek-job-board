# ABOUTME: Runs the polite client against a real public job board feed through the real transport.
# ABOUTME: A stale cache entry is revalidated with If-None-Match and the server answers a real 304.
import json
from pathlib import Path

import pytest

from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.ingest.safe_http import FetchLimits

pytestmark = pytest.mark.needs_network

FEED_URL = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
LIMITS = FetchLimits(content_types=frozenset({"application/json"}))


def test_a_real_feed_is_fetched_then_revalidated_with_a_real_304(tmp_path: Path) -> None:
    clock = SystemClock()
    limiter = HostRateLimiter(clock, delay_seconds=1.0)
    cache = ResponseCache(tmp_path / "cache")

    first = PoliteClient(FetchPolicy(), cache, limiter, clock, limits=LIMITS).get(FEED_URL)

    assert first.from_cache is False
    assert first.status == 200
    assert first.url == FEED_URL
    assert first.etag is not None
    assert isinstance(json.loads(first.body)["jobs"], list)

    stale_policy = FetchPolicy(refresh_interval_seconds=0.001)
    second = PoliteClient(stale_policy, cache, limiter, clock, limits=LIMITS).get(FEED_URL)

    assert second.from_cache is True
    assert second.status == 304
    assert second.body == first.body
    assert second.etag == first.etag
    assert second.fetched_at > first.fetched_at
