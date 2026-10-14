# ABOUTME: Tests the polite fetch building blocks: the per host rate limiter and the fetch policy.
# ABOUTME: Covers delays on a manual clock, the real clock, validation, env parsing and backoff.
import math
import threading
import time
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest

from cypress_creek.discovery.fetch_policy import (
    MAX_RETRIES_CAP,
    FetchConfigError,
    FetchPolicy,
    parse_retry_after,
)
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock, SystemClock

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


# ---- rate limiter ----


def test_two_requests_to_one_host_are_at_least_the_delay_apart() -> None:
    clock = ManualClock()
    limiter = HostRateLimiter(clock, delay_seconds=1.0)
    limiter.wait("example.org")
    first = clock.monotonic()
    limiter.wait("example.org")
    assert clock.monotonic() - first >= 1.0


def test_the_first_request_to_a_host_does_not_wait() -> None:
    clock = ManualClock()
    HostRateLimiter(clock, delay_seconds=5.0).wait("example.org")
    assert clock.sleeps == []


def test_only_the_remaining_delay_is_slept() -> None:
    clock = ManualClock()
    limiter = HostRateLimiter(clock, delay_seconds=1.0)
    limiter.wait("example.org")
    clock.advance(0.25)
    limiter.wait("example.org")
    assert clock.sleeps == [pytest.approx(0.75)]


def test_no_sleep_when_the_delay_already_passed() -> None:
    clock = ManualClock()
    limiter = HostRateLimiter(clock, delay_seconds=1.0)
    limiter.wait("example.org")
    clock.advance(3.0)
    limiter.wait("example.org")
    assert clock.sleeps == []


def test_different_hosts_do_not_wait_for_each_other() -> None:
    clock = ManualClock()
    limiter = HostRateLimiter(clock, delay_seconds=1.0)
    limiter.wait("a.example.org")
    limiter.wait("b.example.org")
    assert clock.sleeps == []


def test_host_names_are_case_folded() -> None:
    clock = ManualClock()
    limiter = HostRateLimiter(clock, delay_seconds=1.0)
    limiter.wait("Example.ORG")
    limiter.wait("example.org")
    assert clock.sleeps == [pytest.approx(1.0)]


@pytest.mark.parametrize("delay", [-1.0, math.nan, math.inf])
def test_the_limiter_rejects_a_bad_delay(delay: float) -> None:
    with pytest.raises(ValueError, match="delay_seconds"):
        HostRateLimiter(ManualClock(), delay_seconds=delay)


def test_the_system_clock_really_sleeps() -> None:
    clock = SystemClock()
    start = time.monotonic()
    clock.sleep(0.05)
    assert time.monotonic() - start >= 0.045


def test_the_limiter_works_on_the_system_clock() -> None:
    limiter = HostRateLimiter(SystemClock(), delay_seconds=0.05)
    limiter.wait("example.org")
    start = time.monotonic()
    limiter.wait("example.org")
    assert time.monotonic() - start >= 0.045


def test_threads_hitting_one_host_are_serialised() -> None:
    clock = ManualClock()
    limiter = HostRateLimiter(clock, delay_seconds=1.0)
    threads = [threading.Thread(target=limiter.wait, args=("example.org",)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert clock.monotonic() >= 3.0
    assert len(clock.sleeps) == 3


# ---- policy validation ----


def test_the_defaults() -> None:
    policy = FetchPolicy()
    assert policy.refresh_interval_seconds == 900
    assert policy.per_host_delay_seconds == 1.0
    assert policy.max_retries == 4
    assert policy.backoff_base_seconds == 1.0
    assert policy.backoff_cap_seconds == 60.0


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf, -math.inf, True, "5", None])
@pytest.mark.parametrize(
    "field",
    [
        "refresh_interval_seconds",
        "per_host_delay_seconds",
        "backoff_base_seconds",
        "backoff_cap_seconds",
    ],
)
def test_seconds_must_be_positive_and_finite(field: str, bad: object) -> None:
    with pytest.raises(ValueError, match=field):
        FetchPolicy(**{field: bad})  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-1, 1.5, True, MAX_RETRIES_CAP + 1, "3", None])
def test_max_retries_must_be_a_bounded_non_negative_int(bad: object) -> None:
    with pytest.raises(ValueError, match="max_retries"):
        FetchPolicy(max_retries=bad)  # type: ignore[arg-type]


def test_zero_retries_and_the_cap_are_allowed() -> None:
    assert FetchPolicy(max_retries=0).max_retries == 0
    assert FetchPolicy(max_retries=MAX_RETRIES_CAP).max_retries == MAX_RETRIES_CAP


def test_the_cap_may_not_be_below_the_base() -> None:
    with pytest.raises(ValueError, match="backoff_cap_seconds"):
        FetchPolicy(backoff_base_seconds=10.0, backoff_cap_seconds=5.0)


# ---- environment ----


def test_an_empty_environment_gives_the_defaults() -> None:
    assert FetchPolicy.from_environment({}) == FetchPolicy()


def test_the_environment_overrides_the_defaults() -> None:
    policy = FetchPolicy.from_environment(
        {
            "CYPRESS_CREEK_FETCH_REFRESH_SECONDS": "60",
            "CYPRESS_CREEK_FETCH_HOST_DELAY_SECONDS": "2.5",
            "CYPRESS_CREEK_FETCH_MAX_RETRIES": "2",
        }
    )
    assert policy.refresh_interval_seconds == 60
    assert policy.per_host_delay_seconds == 2.5
    assert policy.max_retries == 2


def test_a_blank_value_means_the_default() -> None:
    assert FetchPolicy.from_environment({"CYPRESS_CREEK_FETCH_MAX_RETRIES": "  "}) == FetchPolicy()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CYPRESS_CREEK_FETCH_REFRESH_SECONDS", "hunter2-secret"),
        ("CYPRESS_CREEK_FETCH_REFRESH_SECONDS", "nan"),
        ("CYPRESS_CREEK_FETCH_REFRESH_SECONDS", "-5"),
        ("CYPRESS_CREEK_FETCH_HOST_DELAY_SECONDS", "inf"),
        ("CYPRESS_CREEK_FETCH_HOST_DELAY_SECONDS", "0"),
        ("CYPRESS_CREEK_FETCH_MAX_RETRIES", "1.5"),
        ("CYPRESS_CREEK_FETCH_MAX_RETRIES", "-1"),
        ("CYPRESS_CREEK_FETCH_MAX_RETRIES", "99"),
        ("CYPRESS_CREEK_FETCH_MAX_RETRIES", "hunter2-secret"),
    ],
)
def test_a_malformed_setting_raises_without_echoing_the_value(name: str, value: str) -> None:
    with pytest.raises(FetchConfigError) as caught:
        FetchPolicy.from_environment({name: value})
    assert name in str(caught.value)
    assert value not in str(caught.value)
    assert isinstance(caught.value, ValueError)


# ---- backoff ----


def test_backoff_grows_exponentially() -> None:
    policy = FetchPolicy(backoff_base_seconds=1.0, backoff_cap_seconds=1000.0)
    delays = [policy.backoff_delay(n, None, 0.0) for n in range(4)]
    assert delays == [0.5, 1.0, 2.0, 4.0]


def test_backoff_is_capped() -> None:
    policy = FetchPolicy(backoff_base_seconds=1.0, backoff_cap_seconds=10.0)
    assert policy.backoff_delay(30, None, 0.99) < 10.0
    assert policy.backoff_delay(10_000, None, 0.0) == 5.0


def test_jitter_spreads_the_delay_inside_the_window() -> None:
    policy = FetchPolicy(backoff_base_seconds=4.0, backoff_cap_seconds=100.0)
    low = policy.backoff_delay(0, None, 0.0)
    high = policy.backoff_delay(0, None, 0.999)
    assert low == 2.0
    assert low < high < 4.0


def test_a_larger_retry_after_wins() -> None:
    policy = FetchPolicy()
    assert policy.backoff_delay(0, 30.0, 0.0) == 30.0


def test_a_smaller_retry_after_does_not_shorten_the_backoff() -> None:
    policy = FetchPolicy(backoff_base_seconds=8.0)
    assert policy.backoff_delay(0, 0.1, 0.0) == 4.0


def test_retry_after_is_itself_capped() -> None:
    policy = FetchPolicy(backoff_cap_seconds=60.0)
    assert policy.backoff_delay(0, 86_400.0, 0.0) == 60.0


@pytest.mark.parametrize("retry_after", [math.nan, math.inf, -5.0])
def test_a_hostile_retry_after_is_ignored(retry_after: float) -> None:
    policy = FetchPolicy()
    assert policy.backoff_delay(0, retry_after, 0.0) == 0.5


@pytest.mark.parametrize(
    ("attempt", "jitter"), [(-1, 0.0), (0, -0.1), (0, 1.0), (0, math.nan), (True, 0.0)]
)
def test_backoff_rejects_bad_arguments(attempt: int, jitter: float) -> None:
    with pytest.raises(ValueError, match="backoff"):
        FetchPolicy().backoff_delay(attempt, None, jitter)


# ---- Retry-After parsing ----


def test_delta_seconds_parse() -> None:
    assert parse_retry_after("120", NOW) == 120.0
    assert parse_retry_after("  7 ", NOW) == 7.0
    assert parse_retry_after("0", NOW) == 0.0


def test_an_http_date_parses_relative_to_now() -> None:
    later = datetime(2026, 1, 2, 3, 6, 5, tzinfo=UTC)
    assert parse_retry_after(format_datetime(later, usegmt=True), NOW) == 120.0


def test_an_http_date_in_the_past_means_retry_now() -> None:
    earlier = datetime(2025, 1, 1, tzinfo=UTC)
    assert parse_retry_after(format_datetime(earlier, usegmt=True), NOW) == 0.0


def test_a_naive_now_is_treated_as_utc() -> None:
    later = datetime(2026, 1, 2, 3, 6, 5, tzinfo=UTC)
    naive_now = NOW.replace(tzinfo=None)
    assert parse_retry_after(format_datetime(later, usegmt=True), naive_now) == 120.0


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "soon",
        "-5",
        "+5",
        "5.5",
        "1e3",
        "nan",
        "inf",
        "-inf",
        "9" * 400,
        "Wed, 99 Foo 2026 99:99:99 GMT",
        "\x00",
        "12\x0034",
        "١٢٣",
    ],
)
def test_garbage_is_none(raw: str | None) -> None:
    assert parse_retry_after(raw, NOW) is None


def test_a_huge_delta_is_finite_so_the_caller_can_cap_it() -> None:
    result = parse_retry_after("999999999999", NOW)
    assert result is not None
    assert math.isfinite(result)
