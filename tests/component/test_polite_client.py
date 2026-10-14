# ABOUTME: Tests the polite client against a real loopback HTTP server through the real transport.
# ABOUTME: The private fetch seam points that transport at the fixture host; no response is faked.
import time
from pathlib import Path

import pytest
from http_support import Requests, http_server, local_target

from cypress_creek import __version__
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import (
    NotFound,
    PoliteClient,
    PoliteFetchError,
    RetriesExhausted,
    UnexpectedNotModified,
)
from cypress_creek.discovery.rate_limiter import Clock, HostRateLimiter, ManualClock, SystemClock
from cypress_creek.ingest.safe_http import FetchLimits, FetchResponse, SafeHttpError, _fetch
from cypress_creek.ingest.url_guard import UrlGuardError

LIMITS = FetchLimits(content_types=frozenset({"text/plain", "application/json"}))
REPO_URL = "https://github.com/jpalicke/cypress-creek-job-board"


class _StampedList(list[tuple[str, dict[str, str]]]):
    """The server's request log, with the server's own arrival time for each request."""

    def __init__(self) -> None:
        super().__init__()
        self.arrivals: list[float] = []

    def append(self, item: tuple[str, dict[str, str]]) -> None:
        self.arrivals.append(time.monotonic())
        super().append(item)


def _stamp_arrivals(requests: Requests) -> _StampedList:
    stamped = _StampedList()
    requests.received = stamped
    return stamped


def _live_fetch(
    url: str, *, limits: FetchLimits, if_none_match: str | None, pass_through_statuses: bool
) -> FetchResponse:
    return _fetch(
        url,
        limits,
        resolve=local_target,
        if_none_match=if_none_match,
        pass_through_statuses=pass_through_statuses,
    )


def _client(
    tmp_path: Path,
    clock: Clock,
    *,
    policy: FetchPolicy | None = None,
    host_delay: float = 1.0,
) -> tuple[PoliteClient, ResponseCache]:
    cache = ResponseCache(tmp_path / "cache")
    client = PoliteClient(
        policy or FetchPolicy(),
        cache,
        HostRateLimiter(clock, delay_seconds=host_delay),
        clock,
        limits=LIMITS,
        fetch=_live_fetch,
        random_source=lambda: 0.0,
    )
    return client, cache


def test_two_requests_to_one_host_are_at_least_one_second_apart(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, SystemClock(), policy=FetchPolicy(refresh_interval_seconds=1e-6))
    with http_server() as (port, requests):
        arrivals = _stamp_arrivals(requests).arrivals
        client.get(f"http://fixture.test:{port}/ok")
        client.get(f"http://fixture.test:{port}/ok")
    assert len(arrivals) == 2
    assert arrivals[1] - arrivals[0] >= 1.0


def test_a_fresh_download_is_cached_and_attributed(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=5000.0)
    client, cache = _client(tmp_path, clock)
    with http_server() as (port, _):
        url = f"http://fixture.test:{port}/etag"
        result = client.get(url)
    assert result.url == url
    assert result.body == b"public posting"
    assert result.etag == '"v1"'
    assert result.status == 200
    assert result.from_cache is False
    assert result.fetched_at == 5000.0
    stored = cache.get(url)
    assert stored is not None
    assert (stored.body, stored.etag, stored.fetched_at) == (b"public posting", '"v1"', 5000.0)


def test_a_second_call_inside_the_refresh_window_makes_no_request(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=5000.0)
    client, _ = _client(tmp_path, clock, policy=FetchPolicy(refresh_interval_seconds=900))
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/etag"
        client.get(url)
        clock.advance(899.0)
        sleeps_before = list(clock.sleeps)
        again = client.get(url)
        assert len(requests.received) == 1
    assert again.from_cache is True
    assert again.body == b"public posting"
    assert again.fetched_at == 5000.0
    assert clock.sleeps == sleeps_before


def test_a_stale_entry_is_revalidated_and_a_304_is_served_from_cache(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=5000.0)
    client, cache = _client(tmp_path, clock, policy=FetchPolicy(refresh_interval_seconds=900))
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/etag"
        client.get(url)
        clock.advance(901.0)
        again = client.get(url)
        sent = [headers.get("if-none-match") for _, headers in requests.received]
    assert sent == [None, '"v1"']
    assert again.from_cache is True
    assert again.status == 304
    assert again.body == b"public posting"
    assert again.etag == '"v1"'
    assert again.fetched_at == 5901.0
    stored = cache.get(url)
    assert stored is not None
    assert (stored.body, stored.etag, stored.fetched_at) == (b"public posting", '"v1"', 5901.0)


def test_a_changed_etag_replaces_the_entry(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=5000.0)
    client, cache = _client(tmp_path, clock)
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/etag"
        cache.put(url, b"old body", '"v0"', 1.0)
        result = client.get(url)
        assert requests.received[0][1]["if-none-match"] == '"v0"'
    assert result.from_cache is False
    assert result.body == b"public posting"
    stored = cache.get(url)
    assert stored is not None
    assert (stored.body, stored.etag, stored.fetched_at) == (b"public posting", '"v1"', 5000.0)


def test_requests_carry_the_honest_user_agent_and_ask_for_gzip(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, ManualClock())
    with http_server() as (port, requests):
        client.get(f"http://fixture.test:{port}/ok")
    headers = requests.received[0][1]
    assert headers["user-agent"] == (
        f"cypress-creek/{__version__} (personal job search tool; +{REPO_URL})"
    )
    assert headers["accept-encoding"] == "gzip"


def test_a_gzip_response_is_decoded_and_cached(tmp_path: Path) -> None:
    client, cache = _client(tmp_path, ManualClock())
    with http_server() as (port, _):
        url = f"http://fixture.test:{port}/gzip"
        result = client.get(url)
    assert result.body == b"public posting"
    stored = cache.get(url)
    assert stored is not None
    assert stored.body == b"public posting"


def test_a_future_dated_entry_is_not_trusted_as_fresh(tmp_path: Path) -> None:
    client, cache = _client(tmp_path, ManualClock(wall_start=5000.0))
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/etag"
        cache.put(url, b"old body", '"v0"', 9000.0)
        result = client.get(url)
        assert len(requests.received) == 1
    assert result.from_cache is False


def test_429_is_retried_then_fails_typed_and_retry_after_is_capped(tmp_path: Path) -> None:
    clock = ManualClock()
    policy = FetchPolicy(max_retries=3, backoff_base_seconds=1.0, backoff_cap_seconds=100.0)
    client, cache = _client(tmp_path, clock, policy=policy, host_delay=0.0)
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/rate-limited"
        with pytest.raises(RetriesExhausted) as caught:
            client.get(url)
        assert len(requests.received) == 4
    assert caught.value.reason_code == "retries_exhausted"
    assert caught.value.last_status == 429
    assert "private throttle details" not in repr(caught.value) + str(caught.value)
    assert cache.get(url) is None
    # Retry-After is 120, larger than every backoff window, so it wins but is capped at 100.
    assert clock.sleeps == [100.0, 100.0, 100.0]


def test_backoff_grows_without_a_retry_after_and_stops_at_the_cap(tmp_path: Path) -> None:
    clock = ManualClock()
    policy = FetchPolicy(max_retries=4, backoff_base_seconds=1.0, backoff_cap_seconds=3.0)
    client, _ = _client(tmp_path, clock, policy=policy, host_delay=0.0)
    with http_server() as (port, requests), pytest.raises(RetriesExhausted) as caught:
        client.get(f"http://fixture.test:{port}/error")
    assert len(requests.received) == 5
    assert caught.value.last_status == 500
    # Jitter source returns 0.0, so each delay is half of its window: 1, 2, 4 capped to 3, 3.
    assert clock.sleeps == [0.5, 1.0, 1.5, 1.5]


def test_503_with_a_retry_after_date_is_honored_up_to_the_cap(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=1_000_000.0)
    policy = FetchPolicy(max_retries=1, backoff_base_seconds=1.0, backoff_cap_seconds=60.0)
    client, _ = _client(tmp_path, clock, policy=policy, host_delay=0.0)
    with http_server() as (port, requests), pytest.raises(RetriesExhausted) as caught:
        client.get(f"http://fixture.test:{port}/unavailable")
    assert len(requests.received) == 2
    assert caught.value.last_status == 503
    assert clock.sleeps == [60.0]


def test_a_retry_after_in_delta_seconds_is_honored(tmp_path: Path) -> None:
    clock = ManualClock()
    policy = FetchPolicy(max_retries=1, backoff_base_seconds=1.0, backoff_cap_seconds=300.0)
    client, _ = _client(tmp_path, clock, policy=policy, host_delay=0.0)
    with http_server() as (port, _), pytest.raises(RetriesExhausted):
        client.get(f"http://fixture.test:{port}/rate-limited")
    assert clock.sleeps == [120.0]


def test_zero_retries_means_one_attempt(tmp_path: Path) -> None:
    clock = ManualClock()
    client, _ = _client(tmp_path, clock, policy=FetchPolicy(max_retries=0), host_delay=0.0)
    with http_server() as (port, requests), pytest.raises(RetriesExhausted):
        client.get(f"http://fixture.test:{port}/error")
    assert len(requests.received) == 1
    assert clock.sleeps == []


def test_every_retry_passes_through_the_limiter(tmp_path: Path) -> None:
    clock = ManualClock()
    attempts: list[float] = []

    def recording_fetch(
        url: str, *, limits: FetchLimits, if_none_match: str | None, pass_through_statuses: bool
    ) -> FetchResponse:
        attempts.append(clock.monotonic())
        return _live_fetch(
            url,
            limits=limits,
            if_none_match=if_none_match,
            pass_through_statuses=pass_through_statuses,
        )

    policy = FetchPolicy(max_retries=3, backoff_base_seconds=0.1, backoff_cap_seconds=0.2)
    client = PoliteClient(
        policy,
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LIMITS,
        fetch=recording_fetch,
        random_source=lambda: 0.0,
    )
    with http_server() as (port, _), pytest.raises(RetriesExhausted):
        client.get(f"http://fixture.test:{port}/error")
    gaps = [later - earlier for earlier, later in zip(attempts, attempts[1:], strict=False)]
    assert len(attempts) == 4
    assert all(gap >= 1.0 for gap in gaps)


def test_a_retry_that_succeeds_returns_the_body(tmp_path: Path) -> None:
    clock = ManualClock()
    calls = {"count": 0}

    def error_then_ok_fetch(
        url: str, *, limits: FetchLimits, if_none_match: str | None, pass_through_statuses: bool
    ) -> FetchResponse:
        calls["count"] += 1
        target = url.replace("/ok", "/error") if calls["count"] == 1 else url
        return _live_fetch(
            target,
            limits=limits,
            if_none_match=if_none_match,
            pass_through_statuses=pass_through_statuses,
        )

    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LIMITS,
        fetch=error_then_ok_fetch,
        random_source=lambda: 0.0,
    )
    with http_server() as (port, requests):
        result = client.get(f"http://fixture.test:{port}/ok")
        assert [path for path, _ in requests.received] == ["/error", "/ok"]
    assert result.body == b"public posting"
    assert result.from_cache is False


def test_a_transport_error_propagates_unchanged(tmp_path: Path) -> None:
    client, cache = _client(tmp_path, ManualClock())
    with http_server() as (port, _):
        url = f"http://fixture.test:{port}/forbidden"
        with pytest.raises(SafeHttpError) as caught:
            client.get(url)
    assert caught.value.reason_code == "http_status"
    assert cache.get(url) is None


def test_a_404_is_a_typed_not_found_that_is_not_cached_or_retried(tmp_path: Path) -> None:
    clock = ManualClock()
    client, cache = _client(tmp_path, clock)
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/missing"
        with pytest.raises(NotFound) as caught:
            client.get(url)
        assert len(requests.received) == 1
    assert isinstance(caught.value, PoliteFetchError)
    assert caught.value.reason_code == "not_found"
    assert vars(caught.value) == {"reason_code": "not_found"}
    assert cache.get(url) is None
    assert clock.sleeps == []


def test_a_404_leaves_an_existing_cache_entry_alone(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=5000.0)
    client, cache = _client(tmp_path, clock, policy=FetchPolicy(refresh_interval_seconds=900))
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/missing"
        cache.put(url, b"older body", '"v0"', 5000.0)
        clock.advance(901.0)
        with pytest.raises(NotFound):
            client.get(url)
        assert [headers.get("if-none-match") for _, headers in requests.received] == ['"v0"']
    stored = cache.get(url)
    assert stored is not None
    assert (stored.body, stored.etag, stored.fetched_at) == (b"older body", '"v0"', 5000.0)


def test_a_404_still_counts_toward_the_per_host_spacing(tmp_path: Path) -> None:
    clock = ManualClock()
    attempts: list[float] = []

    def recording_fetch(
        url: str, *, limits: FetchLimits, if_none_match: str | None, pass_through_statuses: bool
    ) -> FetchResponse:
        attempts.append(clock.monotonic())
        return _live_fetch(
            url,
            limits=limits,
            if_none_match=if_none_match,
            pass_through_statuses=pass_through_statuses,
        )

    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LIMITS,
        fetch=recording_fetch,
        random_source=lambda: 0.0,
    )
    with http_server() as (port, _):
        for _attempt in range(2):
            with pytest.raises(NotFound):
                client.get(f"http://fixture.test:{port}/missing")
    assert len(attempts) == 2
    assert attempts[1] - attempts[0] >= 1.0


def test_the_ssrf_guard_stays_in_charge(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, ManualClock())
    with http_server() as (port, requests), pytest.raises(UrlGuardError):
        client.get(f"http://127.0.0.1:{port}/ok")
    assert requests.received == []


def test_a_304_with_nothing_cached_is_a_typed_error(tmp_path: Path) -> None:
    def always_conditional(
        url: str, *, limits: FetchLimits, if_none_match: str | None, pass_through_statuses: bool
    ) -> FetchResponse:
        return _live_fetch(
            url, limits=limits, if_none_match='"v1"', pass_through_statuses=pass_through_statuses
        )

    cache = ResponseCache(tmp_path / "cache")
    clock = ManualClock()
    client = PoliteClient(
        FetchPolicy(),
        cache,
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LIMITS,
        fetch=always_conditional,
    )
    with http_server() as (port, _):
        url = f"http://fixture.test:{port}/etag"
        with pytest.raises(UnexpectedNotModified) as caught:
            client.get(url)
    assert caught.value.reason_code == "unexpected_not_modified"
    assert cache.get(url) is None
