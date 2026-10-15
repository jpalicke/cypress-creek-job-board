# ABOUTME: Tests the Greenhouse adapter with the real polite client and guarded transport.
# ABOUTME: A real loopback server answers; the fetch seam only points the transport at it.
import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from http_support import http_server, local_target

from cypress_creek.discovery.adapters.base import (
    BoardFetch,
    BoardNotFound,
    ExistenceResult,
    FeedSchemaError,
    ListingState,
    SkippedJob,
    SkipReason,
)
from cypress_creek.discovery.adapters.greenhouse import (
    GREENHOUSE_FETCH_LIMITS,
    GreenhouseAdapter,
)
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.ingest.safe_http import FetchLimits, FetchResponse, SafeHttpError, _fetch

FIXTURE = Path(__file__).parent.parent / "fixtures" / "greenhouse" / "board_responses.json"
RESPONSES = json.loads(FIXTURE.read_text(encoding="utf-8"))
JOBS = json.dumps(RESPONSES["jobs_response"]).encode("utf-8")
BOARD = json.dumps(RESPONSES["board_response"]).encode("utf-8")
ROUTES = {"/v1/boards/examplecoboard/jobs": JOBS, "/v1/boards/examplecoboard": BOARD}
WALL_START = 1_760_000_000.0


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


def _adapter(tmp_path: Path, port: int, clock: ManualClock | None = None) -> GreenhouseAdapter:
    clock = clock or ManualClock(wall_start=WALL_START)
    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=GREENHOUSE_FETCH_LIMITS,
        fetch=_live_fetch,
        random_source=lambda: 0.0,
    )
    return GreenhouseAdapter(client, base_url=f"http://fixture.test:{port}")


def _board_routes(total: int, bad: dict[int, Callable[[dict[str, Any]], None]]) -> dict[str, bytes]:
    """A served board of total jobs shaped like the fixture's first job, bad ones mutated."""
    template = RESPONSES["jobs_response"]["jobs"][0]
    jobs = []
    for index in range(total):
        job = copy.deepcopy(template)
        job["id"] = 6000 + index
        job["absolute_url"] = f"https://boards.example.test/examplecoboard/jobs/{6000 + index}"
        if index in bad:
            bad[index](job)
        jobs.append(job)
    return {"/v1/boards/examplecoboard/jobs": json.dumps({"jobs": jobs}).encode("utf-8")}


def _bad_title(job: dict[str, Any]) -> None:
    job["title"] = 12


def test_fetch_board_returns_normalized_listings(tmp_path: Path) -> None:
    with http_server(ROUTES) as (port, requests):
        fetch = _adapter(tmp_path, port).fetch_board("ExampleCoBoard")
        assert [path for path, _ in requests.received] == [
            "/v1/boards/examplecoboard/jobs?content=true"
        ]
    assert isinstance(fetch, BoardFetch)
    assert fetch.skipped == ()
    listings = fetch.listings
    assert [item.id for item in listings] == [
        "greenhouse:examplecoboard:4100001",
        "greenhouse:examplecoboard:4100002",
        "greenhouse:examplecoboard:4100003",
    ]
    first = listings[0]
    assert first.title == "Kite Platform Engineer"
    assert first.content_text.startswith("Who we are\nExample Co builds paper airplanes & kites.")
    assert first.fetched_at.timestamp() == WALL_START
    assert first.state is ListingState.NEW


def test_a_missing_board_raises_board_not_found(tmp_path: Path) -> None:
    with http_server(ROUTES) as (port, _), pytest.raises(BoardNotFound) as caught:
        _adapter(tmp_path, port).fetch_board("ghostboard")
    assert (caught.value.ats, caught.value.slug) == ("greenhouse", "ghostboard")


def test_probe_reports_the_organization_name(tmp_path: Path) -> None:
    with http_server(ROUTES) as (port, requests):
        result = _adapter(tmp_path, port).probe("examplecoboard")
        assert [path for path, _ in requests.received] == ["/v1/boards/examplecoboard"]
    assert result == ExistenceResult(found=True, organization_name="Example Co")


def test_probe_of_a_missing_board_is_not_an_error(tmp_path: Path) -> None:
    with http_server(ROUTES) as (port, _):
        result = _adapter(tmp_path, port).probe("ghostboard")
    assert result == ExistenceResult(found=False, organization_name=None)


FORBIDDEN = {
    "/v1/boards/lockedboard": "403 Forbidden",
    "/v1/boards/lockedboard/jobs": "403 Forbidden",
    "/v1/boards/goneboard": "410 Gone",
    "/v1/boards/goneboard/jobs": "410 Gone",
}


@pytest.mark.parametrize("slug", ["lockedboard", "goneboard"])
def test_a_refused_board_is_a_transport_error_not_a_missing_board(
    tmp_path: Path, slug: str
) -> None:
    with http_server(ROUTES, FORBIDDEN) as (port, _), pytest.raises(SafeHttpError) as caught:
        _adapter(tmp_path, port).fetch_board(slug)
    assert caught.value.reason_code == "http_status"


@pytest.mark.parametrize("slug", ["lockedboard", "goneboard"])
def test_probe_of_a_refused_board_is_not_reported_as_missing(tmp_path: Path, slug: str) -> None:
    with http_server(ROUTES, FORBIDDEN) as (port, _), pytest.raises(SafeHttpError) as caught:
        _adapter(tmp_path, port).probe(slug)
    assert caught.value.reason_code == "http_status"


def test_a_hostile_slug_cannot_change_the_path_or_query(tmp_path: Path) -> None:
    with http_server(ROUTES) as (port, requests), pytest.raises(BoardNotFound):
        _adapter(tmp_path, port).fetch_board("examplecoboard/../x?content=false#frag")
    assert [path for path, _ in requests.received] == [
        "/v1/boards/examplecoboard%2F..%2Fx%3Fcontent%3Dfalse%23frag/jobs?content=true"
    ]


def test_one_bad_job_in_twenty_is_skipped_and_the_rest_are_listed(tmp_path: Path) -> None:
    routes = _board_routes(20, {11: _bad_title})
    with http_server(routes) as (port, _):
        fetch = _adapter(tmp_path, port).fetch_board("examplecoboard")
    assert isinstance(fetch, BoardFetch)
    assert len(fetch.listings) == 19
    assert fetch.skipped == (
        SkippedJob(index=11, job_id="6011", field="title", reason_code=SkipReason.INVALID_FIELD),
    )
    assert "greenhouse:examplecoboard:6011" not in {item.id for item in fetch.listings}


def test_a_board_that_loses_too_many_jobs_fails_with_a_schema_error(tmp_path: Path) -> None:
    routes = _board_routes(20, {1: _bad_title, 6: _bad_title, 12: _bad_title})
    with http_server(routes) as (port, _), pytest.raises(FeedSchemaError) as caught:
        _adapter(tmp_path, port).fetch_board("examplecoboard")
    assert caught.value.field == "jobs"


def test_a_cached_board_with_a_skipped_job_gives_the_same_result(tmp_path: Path) -> None:
    routes = _board_routes(20, {11: _bad_title})
    with http_server(routes) as (port, requests):
        adapter = _adapter(tmp_path, port)
        first = adapter.fetch_board("examplecoboard")
        second = adapter.fetch_board("examplecoboard")
        assert len(requests.received) == 1
    assert len(second.listings) == 19
    assert second.skipped == first.skipped
    assert len(second.skipped) == 1


def test_a_second_fetch_is_served_from_the_cache(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=WALL_START)
    with http_server(ROUTES) as (port, requests):
        adapter = _adapter(tmp_path, port, clock)
        first = adapter.fetch_board("examplecoboard")
        second = adapter.fetch_board("examplecoboard")
        assert len(requests.received) == 1
    assert second == first


def test_other_transport_errors_propagate_unchanged(tmp_path: Path) -> None:
    routes = {"/v1/boards/examplecoboard/jobs": JOBS}
    limits = FetchLimits(content_types=frozenset({"text/plain"}))
    clock = ManualClock(wall_start=WALL_START)
    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=limits,
        fetch=_live_fetch,
    )
    with http_server(routes) as (port, _), pytest.raises(SafeHttpError) as caught:
        GreenhouseAdapter(client, base_url=f"http://fixture.test:{port}").fetch_board(
            "examplecoboard"
        )
    assert caught.value.reason_code == "unsupported_content"
