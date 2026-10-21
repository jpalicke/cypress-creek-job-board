# ABOUTME: Tests the Ashby adapter with the real polite client and guarded transport.
# ABOUTME: A real loopback server answers, including a weak ETag and a 304 revalidation.
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from http_support import Requests, http_server, local_target

from cypress_creek.discovery.adapters.ashby import (
    ASHBY_FETCH_LIMITS,
    DEFAULT_BASE_URL,
    AshbyAdapter,
)
from cypress_creek.discovery.adapters.base import (
    BoardAdapter,
    BoardFetch,
    BoardNotFound,
    ExistenceResult,
    FeedSchemaError,
)
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient, RetriesExhausted
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.ingest.safe_http import FetchResponse, SafeHttpError, _fetch

FIXTURE = Path(__file__).parent.parent / "fixtures" / "ashby" / "ashby_board.json"
RECORDED: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
WALL_START = 1_760_000_000.0
SLUG = "examplecoboard"
ROUTE = f"/board/{SLUG}"
WEAK_ETAG = 'W/"abc123"'
PAST_THE_REFRESH_WINDOW = 10_000.0


def _live_fetch(
    url: str, *, limits: Any, if_none_match: str | None, pass_through_statuses: bool
) -> FetchResponse:
    return _fetch(
        url,
        limits,
        resolve=local_target,
        if_none_match=if_none_match,
        pass_through_statuses=pass_through_statuses,
    )


def _client(tmp_path: Path, clock: ManualClock) -> PoliteClient:
    return PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=ASHBY_FETCH_LIMITS,
        fetch=_live_fetch,
        random_source=lambda: 0.0,
    )


def _adapter(tmp_path: Path, port: int, clock: ManualClock | None = None) -> AshbyAdapter:
    manual = clock or ManualClock(wall_start=WALL_START)
    return AshbyAdapter(_client(tmp_path, manual), base_url=f"http://fixture.test:{port}/board")


def _board(slug: str = SLUG, body: object = RECORDED) -> dict[str, bytes]:
    return {f"/board/{slug}": json.dumps(body).encode("utf-8")}


def _paths(requests: Requests) -> list[str]:
    return [path for path, _ in requests.received]


def _recorded_with(mutate: Any) -> dict[str, Any]:
    board = copy.deepcopy(RECORDED)
    mutate(board)
    return board


def test_the_fetch_limits_allow_only_json_and_a_generous_board() -> None:
    assert ASHBY_FETCH_LIMITS.content_types == frozenset({"application/json"})
    assert ASHBY_FETCH_LIMITS.total_timeout == 60.0
    # A real board of 63 jobs was 1.95 MB.
    assert ASHBY_FETCH_LIMITS.max_wire_bytes >= 8 * 1_950_000
    assert ASHBY_FETCH_LIMITS.max_decoded_bytes >= 8 * 1_950_000


def test_the_default_base_url_is_the_public_job_board_api() -> None:
    assert DEFAULT_BASE_URL == "https://api.ashbyhq.com/posting-api/job-board"


def test_the_adapter_satisfies_the_board_adapter_contract(tmp_path: Path) -> None:
    adapter: BoardAdapter = AshbyAdapter(_client(tmp_path, ManualClock()))
    assert callable(adapter.fetch_board) and callable(adapter.probe)


def test_a_board_is_one_plain_get_with_no_query(tmp_path: Path) -> None:
    with http_server(_board()) as (port, requests):
        fetch = _adapter(tmp_path, port).fetch_board("ExampleCoBoard")
        assert _paths(requests) == [ROUTE]
        assert requests.methods == ["GET"]
    assert isinstance(fetch, BoardFetch)
    assert fetch.skipped == ()
    assert fetch.unlisted == 0
    assert [item.id for item in fetch.listings] == [
        f"ashby:{SLUG}:{job['id']}" for job in RECORDED["jobs"]
    ]
    assert len(fetch.listings) == 3
    assert {item.slug for item in fetch.listings} == {SLUG}
    assert fetch.listings[0].fetched_at.timestamp() == WALL_START


def test_an_unlisted_job_is_counted_and_not_a_listing(tmp_path: Path) -> None:
    board = _recorded_with(lambda data: data["jobs"][1].update(isListed=False))
    with http_server(_board(body=board)) as (port, _):
        fetch = _adapter(tmp_path, port).fetch_board(SLUG)
    assert fetch.unlisted == 1
    assert fetch.skipped == ()
    assert [item.id for item in fetch.listings] == [
        f"ashby:{SLUG}:{RECORDED['jobs'][0]['id']}",
        f"ashby:{SLUG}:{RECORDED['jobs'][2]['id']}",
    ]


def test_an_empty_board_is_an_empty_fetch(tmp_path: Path) -> None:
    with http_server(_board(body={"jobs": []})) as (port, _):
        fetch = _adapter(tmp_path, port).fetch_board(SLUG)
    assert fetch == BoardFetch(listings=(), skipped=())


def test_a_missing_board_raises_board_not_found_and_probe_says_not_found(tmp_path: Path) -> None:
    with http_server(_board("other")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        with pytest.raises(BoardNotFound) as caught:
            adapter.fetch_board("ghostboard")
        result = adapter.probe("ghostboard")
        assert _paths(requests) == ["/board/ghostboard", "/board/ghostboard"]
    assert (caught.value.ats, caught.value.slug) == ("ashby", "ghostboard")
    assert result == ExistenceResult(found=False, organization_name=None)


def test_a_missing_board_is_asked_again_because_a_404_is_not_cached(tmp_path: Path) -> None:
    with http_server(_board("other")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        for _ in range(2):
            with pytest.raises(BoardNotFound):
                adapter.fetch_board("ghostboard")
        assert adapter.probe("ghostboard").found is False
        assert len(requests.received) == 3
    assert (
        ResponseCache(tmp_path / "cache").get(f"http://fixture.test:{port}/board/ghostboard")
        is None
    )


@pytest.mark.parametrize("status", ["403 Forbidden", "410 Gone"])
def test_a_refused_board_is_a_transport_error_not_a_missing_board(
    tmp_path: Path, status: str
) -> None:
    with http_server(_board("other"), {ROUTE: status}) as (port, _):
        adapter = _adapter(tmp_path, port)
        with pytest.raises(SafeHttpError) as fetch_caught:
            adapter.fetch_board(SLUG)
        with pytest.raises(SafeHttpError) as probe_caught:
            adapter.probe(SLUG)
    assert fetch_caught.value.reason_code == "http_status"
    assert probe_caught.value.reason_code == "http_status"


def test_a_server_error_that_outlasts_the_retries_propagates_from_both(tmp_path: Path) -> None:
    with http_server(_board("other"), {ROUTE: "500 Internal Server Error"}) as (port, _):
        adapter = _adapter(tmp_path, port)
        with pytest.raises(RetriesExhausted) as fetch_caught:
            adapter.fetch_board(SLUG)
        with pytest.raises(RetriesExhausted) as probe_caught:
            adapter.probe(SLUG)
    assert fetch_caught.value.last_status == 500
    assert probe_caught.value.last_status == 500


def test_probe_of_a_board_is_found_without_a_name(tmp_path: Path) -> None:
    with http_server(_board()) as (port, requests):
        result = _adapter(tmp_path, port).probe("ExampleCoBoard")
        assert _paths(requests) == [ROUTE]
        assert requests.methods == ["GET"]
    assert result == ExistenceResult(found=True, organization_name=None)


def test_probe_of_a_board_with_no_jobs_is_found(tmp_path: Path) -> None:
    with http_server(_board(body={"jobs": []})) as (port, _):
        result = _adapter(tmp_path, port).probe(SLUG)
    assert result == ExistenceResult(found=True, organization_name=None)


@pytest.mark.parametrize(
    ("body", "field"),
    [([], "$"), ("text", "$"), (None, "$"), ({"jobs": 5}, "jobs"), ({"ok": False}, "jobs")],
)
def test_probe_of_a_200_that_is_not_a_board_is_a_schema_error(
    tmp_path: Path, body: object, field: str
) -> None:
    with http_server(_board(body=body)) as (port, _), pytest.raises(FeedSchemaError) as caught:
        _adapter(tmp_path, port).probe(SLUG)
    assert caught.value.field == field


def test_probe_checks_the_shape_of_the_board_but_not_each_job(tmp_path: Path) -> None:
    body = {"jobs": [None, 5, {"id": "not plain!", "isListed": "yes"}]}
    with http_server(_board(body=body)) as (port, _):
        result = _adapter(tmp_path, port).probe(SLUG)
    assert result == ExistenceResult(found=True, organization_name=None)


def test_a_fetch_after_a_probe_is_served_from_the_cache(tmp_path: Path) -> None:
    with http_server(_board()) as (port, requests):
        adapter = _adapter(tmp_path, port)
        adapter.probe(SLUG)
        fetch = adapter.fetch_board(SLUG)
        assert _paths(requests) == [ROUTE]
    assert len(fetch.listings) == 3


def test_a_second_fetch_is_served_from_the_cache(tmp_path: Path) -> None:
    with http_server(_board()) as (port, requests):
        adapter = _adapter(tmp_path, port)
        first = adapter.fetch_board(SLUG)
        second = adapter.fetch_board(SLUG)
        assert len(requests.received) == 1
    assert second == first


def test_a_weak_etag_is_sent_back_unchanged_and_a_304_yields_the_cached_board(
    tmp_path: Path,
) -> None:
    clock = ManualClock(wall_start=WALL_START)
    with http_server(_board(), etags={ROUTE: WEAK_ETAG}) as (port, requests):
        adapter = _adapter(tmp_path, port, clock)
        first = adapter.fetch_board(SLUG)
        stored = ResponseCache(tmp_path / "cache").get(f"http://fixture.test:{port}{ROUTE}")
        clock.advance(PAST_THE_REFRESH_WINDOW)
        second = adapter.fetch_board(SLUG)
        assert [headers.get("if-none-match") for _, headers in requests.received] == [
            None,
            WEAK_ETAG,
        ]
        assert requests.methods == ["GET", "GET"]
        revalidated = ResponseCache(tmp_path / "cache").get(f"http://fixture.test:{port}{ROUTE}")
    assert stored is not None and stored.etag == WEAK_ETAG
    assert revalidated is not None and revalidated.etag == WEAK_ETAG
    assert revalidated.fetched_at > stored.fetched_at
    assert [item.id for item in second.listings] == [item.id for item in first.listings]
    assert [item.content_hash for item in second.listings] == [
        item.content_hash for item in first.listings
    ]
    assert second.listings[0].fetched_at > first.listings[0].fetched_at


def test_a_probe_after_the_window_also_revalidates_with_the_weak_etag(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=WALL_START)
    with http_server(_board(), etags={ROUTE: WEAK_ETAG}) as (port, requests):
        adapter = _adapter(tmp_path, port, clock)
        adapter.fetch_board(SLUG)
        clock.advance(PAST_THE_REFRESH_WINDOW)
        result = adapter.probe(SLUG)
        assert requests.received[1][1].get("if-none-match") == WEAK_ETAG
    assert result.found is True


def test_a_slug_is_normalized_like_a_board_everywhere(tmp_path: Path) -> None:
    with http_server(_board()) as (port, requests):
        adapter = _adapter(tmp_path, port)
        fetch = adapter.fetch_board("  ExampleCoBoard ")
        adapter.probe("EXAMPLECOBOARD")
        assert _paths(requests) == [ROUTE]
    assert {item.slug for item in fetch.listings} == {SLUG}
    assert all(item.id.startswith(f"ashby:{SLUG}:") for item in fetch.listings)


def test_a_hostile_slug_cannot_change_the_path_or_query(tmp_path: Path) -> None:
    quoted = "examplecoboard%2F..%2Fx%3Fmode%3Dxml%23frag"
    with http_server(_board("other")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        with pytest.raises(BoardNotFound):
            adapter.fetch_board("examplecoboard/../x?mode=xml#frag")
        assert adapter.probe("examplecoboard/../x?mode=xml#frag").found is False
        assert _paths(requests) == [f"/board/{quoted}"] * 2


def test_the_base_url_override_is_honored_and_a_trailing_slash_is_dropped(tmp_path: Path) -> None:
    routes = {f"/elsewhere/{SLUG}": json.dumps(RECORDED).encode("utf-8")}
    with http_server(routes) as (port, requests):
        adapter = AshbyAdapter(
            _client(tmp_path, ManualClock(wall_start=WALL_START)),
            base_url=f"http://fixture.test:{port}/elsewhere/",
        )
        fetch = adapter.fetch_board(SLUG)
        assert _paths(requests) == [f"/elsewhere/{SLUG}"]
    assert len(fetch.listings) == 3


@pytest.mark.parametrize(
    ("body", "field"),
    [([], "$"), ("text", "$"), (None, "$"), ({"jobs": 5}, "jobs"), ({"other": []}, "jobs")],
)
def test_a_hostile_200_body_is_a_schema_error(tmp_path: Path, body: object, field: str) -> None:
    with http_server(_board(body=body)) as (port, _), pytest.raises(FeedSchemaError) as caught:
        _adapter(tmp_path, port).fetch_board(SLUG)
    assert caught.value.field == field
