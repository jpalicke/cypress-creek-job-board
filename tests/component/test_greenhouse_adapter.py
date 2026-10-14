# ABOUTME: Tests the Greenhouse adapter with the real polite client and guarded transport.
# ABOUTME: A real loopback server answers; the fetch seam only points the transport at it.
import json
from pathlib import Path

import pytest
from http_support import http_server, local_target

from cypress_creek.discovery.adapters.base import BoardNotFound, ExistenceResult, ListingState
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


def test_fetch_board_returns_normalized_listings(tmp_path: Path) -> None:
    with http_server(ROUTES) as (port, requests):
        listings = _adapter(tmp_path, port).fetch_board("ExampleCoBoard")
        assert [path for path, _ in requests.received] == [
            "/v1/boards/examplecoboard/jobs?content=true"
        ]
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
