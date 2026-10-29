# ABOUTME: Tests the Lever adapter with the real polite client and guarded transport.
# ABOUTME: A real loopback server answers on a US and an EU path prefix.
import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from http_support import Requests, http_server, local_target

from cypress_creek.discovery.adapters.base import (
    BoardFetch,
    BoardNotFound,
    ExistenceResult,
    FeedSchemaError,
    SkippedJob,
    SkipReason,
)
from cypress_creek.discovery.adapters.lever import (
    LEVER_FETCH_LIMITS,
    MAX_PAGES,
    LeverAdapter,
    LeverRegion,
)
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient, RetriesExhausted
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.ingest.safe_http import FetchResponse, SafeHttpError, _fetch

FIXTURE = Path(__file__).parent.parent / "fixtures" / "lever" / "palantir_page.json"
RECORDED: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
WALL_START = 1_760_000_000.0
SLUG = "examplecoboard"

Mutation = Callable[[dict[str, Any]], None]


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


def _client(tmp_path: Path) -> PoliteClient:
    clock = ManualClock(wall_start=WALL_START)
    return PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LEVER_FETCH_LIMITS,
        fetch=_live_fetch,
        random_source=lambda: 0.0,
    )


def _adapter(tmp_path: Path, port: int, page_size: int = 100) -> LeverAdapter:
    base = f"http://fixture.test:{port}"
    return LeverAdapter(
        _client(tmp_path),
        us_base_url=f"{base}/us",
        eu_base_url=f"{base}/eu",
        page_size=page_size,
    )


def _posting(number: int, mutate: Mutation | None = None) -> dict[str, Any]:
    """A posting shaped like a recorded one, with its own plain id."""
    posting = copy.deepcopy(RECORDED[number % len(RECORDED)])
    posting["id"] = f"posting-{number}"
    posting["hostedUrl"] = f"https://jobs.example.test/{SLUG}/posting-{number}"
    if mutate is not None:
        mutate(posting)
    return posting


def _bad_text(posting: dict[str, Any]) -> None:
    posting["text"] = 12


def _query(page_size: int, skip: int) -> str:
    return f"?mode=json&limit={page_size}&skip={skip}"


def _pages(
    region: str, pages: list[list[dict[str, Any]]], page_size: int, slug: str = SLUG
) -> dict[str, bytes]:
    """Routes that serve each page of postings at its exact skip."""
    return {
        f"/{region}/{slug}{_query(page_size, index * page_size)}": json.dumps(page).encode("utf-8")
        for index, page in enumerate(pages)
    }


def _probe_route(region: str, slug: str = SLUG) -> dict[str, bytes]:
    return {f"/{region}/{slug}{_query(1, 0)}": b"[]"}


def _paths(requests: Requests) -> list[str]:
    return [path for path, _ in requests.received]


def test_the_fetch_limits_allow_only_json_and_a_generous_page() -> None:
    assert LEVER_FETCH_LIMITS.content_types == frozenset({"application/json"})
    assert LEVER_FETCH_LIMITS.total_timeout == 60.0
    # A real page of 100 postings was 1.9 MB.
    assert LEVER_FETCH_LIMITS.max_wire_bytes >= 8 * 1_940_782
    assert LEVER_FETCH_LIMITS.max_decoded_bytes >= 8 * 1_940_782


def test_regions_name_the_two_lever_hosts() -> None:
    assert [region.value for region in LeverRegion] == ["us", "eu"]


@pytest.mark.parametrize("page_size", [0, -1, 101, 1000])
def test_a_page_size_outside_one_to_one_hundred_is_refused(tmp_path: Path, page_size: int) -> None:
    with pytest.raises(ValueError, match="page_size"):
        LeverAdapter(_client(tmp_path), page_size=page_size)


@pytest.mark.parametrize("page_size", [1, 100])
def test_a_page_size_at_the_edges_is_accepted(tmp_path: Path, page_size: int) -> None:
    LeverAdapter(_client(tmp_path), page_size=page_size)


def test_a_single_page_board_is_one_request_with_exact_params(tmp_path: Path) -> None:
    routes = _pages("us", [RECORDED], 100)
    with http_server(routes) as (port, requests):
        fetch = _adapter(tmp_path, port).fetch_board("ExampleCoBoard")
        assert _paths(requests) == [f"/us/{SLUG}?mode=json&limit=100&skip=0"]
        assert requests.methods == ["GET"]
    assert isinstance(fetch, BoardFetch)
    assert fetch.skipped == ()
    assert [item.id for item in fetch.listings] == [
        f"lever:{SLUG}:{posting['id']}" for posting in RECORDED
    ]
    assert fetch.listings[0].fetched_at.timestamp() == WALL_START


def test_a_multi_page_board_is_every_page_in_order(tmp_path: Path) -> None:
    postings = [_posting(number) for number in range(5)]
    routes = _pages("us", [postings[0:2], postings[2:4], postings[4:]], 2)
    with http_server(routes) as (port, requests):
        fetch = _adapter(tmp_path, port, page_size=2).fetch_board(SLUG)
        assert _paths(requests) == [
            f"/us/{SLUG}?mode=json&limit=2&skip=0",
            f"/us/{SLUG}?mode=json&limit=2&skip=2",
            f"/us/{SLUG}?mode=json&limit=2&skip=4",
        ]
        assert set(requests.methods) == {"GET"}
    assert [item.id for item in fetch.listings] == [f"lever:{SLUG}:posting-{n}" for n in range(5)]


def test_a_short_page_ends_the_board_without_another_request(tmp_path: Path) -> None:
    postings = [_posting(number) for number in range(4)]
    routes = _pages("us", [postings[0:3], postings[3:]], 3)
    with http_server(routes) as (port, requests):
        fetch = _adapter(tmp_path, port, page_size=3).fetch_board(SLUG)
        assert len(requests.received) == 2
    assert len(fetch.listings) == 4


def test_an_empty_page_after_full_pages_ends_the_board(tmp_path: Path) -> None:
    postings = [_posting(number) for number in range(4)]
    routes = _pages("us", [postings[0:2], postings[2:4], []], 2)
    with http_server(routes) as (port, requests):
        fetch = _adapter(tmp_path, port, page_size=2).fetch_board(SLUG)
        assert len(requests.received) == 3
    assert len(fetch.listings) == 4


def test_an_empty_board_is_an_empty_fetch(tmp_path: Path) -> None:
    routes = _pages("us", [[]], 100)
    with http_server(routes) as (port, _):
        fetch = _adapter(tmp_path, port).fetch_board(SLUG)
    assert fetch == BoardFetch(listings=(), skipped=())


def test_a_board_that_is_full_at_the_page_cap_fails_instead_of_truncating(tmp_path: Path) -> None:
    pages = [[_posting(2 * page), _posting(2 * page + 1)] for page in range(MAX_PAGES)]
    routes = _pages("us", pages, 2)
    with http_server(routes) as (port, requests), pytest.raises(FeedSchemaError) as caught:
        _adapter(tmp_path, port, page_size=2).fetch_board(SLUG)
    assert caught.value.field == "jobs"
    assert len(requests.received) == MAX_PAGES


def test_a_page_repeated_forever_still_hits_the_page_cap(tmp_path: Path) -> None:
    same = [_posting(0), _posting(1)]
    routes = _pages("us", [same] * MAX_PAGES, 2)
    with http_server(routes) as (port, requests), pytest.raises(FeedSchemaError) as caught:
        _adapter(tmp_path, port, page_size=2).fetch_board(SLUG)
    assert caught.value.field == "jobs"
    assert len(requests.received) == MAX_PAGES


def test_a_board_that_ends_exactly_at_the_page_cap_is_complete(tmp_path: Path) -> None:
    pages = [[_posting(2 * page), _posting(2 * page + 1)] for page in range(MAX_PAGES - 1)]
    pages.append([_posting(1000)])
    routes = _pages("us", pages, 2)
    with http_server(routes) as (port, requests):
        fetch = _adapter(tmp_path, port, page_size=2).fetch_board(SLUG)
        assert len(requests.received) == MAX_PAGES
    assert len(fetch.listings) == 2 * (MAX_PAGES - 1) + 1


def test_a_posting_repeated_on_a_later_page_keeps_the_first(tmp_path: Path) -> None:
    first = [_posting(0), _posting(1)]
    shifted_copy = _posting(1, lambda posting: posting.update(text="Shifted copy"))
    routes = _pages("us", [first, [shifted_copy, _posting(2)], [_posting(3)]], 2)
    with http_server(routes) as (port, _):
        fetch = _adapter(tmp_path, port, page_size=2).fetch_board(SLUG)
    assert [item.id for item in fetch.listings] == [f"lever:{SLUG}:posting-{n}" for n in range(4)]
    assert fetch.listings[1].title != "Shifted copy"


def test_the_skip_budget_is_applied_once_over_the_whole_board(tmp_path: Path) -> None:
    # Two bad postings on the second page of ten would fail a per page budget (20 percent).
    # Over the whole board of 20 they are 10 percent, which is within the budget.
    postings = [_posting(n, _bad_text if n in {12, 15} else None) for n in range(20)]
    routes = _pages("us", [postings[:10], postings[10:], []], 10)
    with http_server(routes) as (port, _):
        fetch = _adapter(tmp_path, port, page_size=10).fetch_board(SLUG)
    assert len(fetch.listings) == 18
    assert fetch.skipped == (
        SkippedJob(
            index=12, job_id="posting-12", field="text", reason_code=SkipReason.INVALID_FIELD
        ),
        SkippedJob(
            index=15, job_id="posting-15", field="text", reason_code=SkipReason.INVALID_FIELD
        ),
    )


def test_bad_postings_spread_over_pages_can_exhaust_the_whole_board_budget(tmp_path: Path) -> None:
    # One bad posting per page of ten passes a per page budget, but four of 30 is over ten percent.
    postings = [_posting(n, _bad_text if n in {1, 11, 21, 29} else None) for n in range(30)]
    routes = _pages("us", [postings[:10], postings[10:20], postings[20:], []], 10)
    with http_server(routes) as (port, _), pytest.raises(FeedSchemaError) as caught:
        _adapter(tmp_path, port, page_size=10).fetch_board(SLUG)
    assert caught.value.field == "jobs"


def test_a_page_that_is_not_an_array_fails_the_board(tmp_path: Path) -> None:
    routes = {f"/us/{SLUG}{_query(100, 0)}": b'{"ok": false}'}
    with http_server(routes) as (port, _), pytest.raises(FeedSchemaError) as caught:
        _adapter(tmp_path, port).fetch_board(SLUG)
    assert caught.value.field == "$"


def test_probe_of_a_us_board_is_found_without_a_name(tmp_path: Path) -> None:
    with http_server(_probe_route("us")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        result = adapter.probe("ExampleCoBoard")
        assert _paths(requests) == [f"/us/{SLUG}?mode=json&limit=1&skip=0"]
        assert requests.methods == ["GET"]
    assert result == ExistenceResult(found=True, organization_name=None)
    assert adapter.region_of(SLUG) is LeverRegion.US
    assert adapter.region_of("EXAMPLECOBOARD") is LeverRegion.US


def test_probe_falls_back_to_eu_after_a_us_404(tmp_path: Path) -> None:
    with http_server(_probe_route("eu")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        result = adapter.probe(SLUG)
        assert _paths(requests) == [
            f"/us/{SLUG}?mode=json&limit=1&skip=0",
            f"/eu/{SLUG}?mode=json&limit=1&skip=0",
        ]
    assert result == ExistenceResult(found=True, organization_name=None)
    assert adapter.region_of(SLUG) is LeverRegion.EU


def test_probe_of_a_board_on_neither_host_is_not_found_and_remembers_nothing(
    tmp_path: Path,
) -> None:
    with http_server(_probe_route("us", "other")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        result = adapter.probe("ghostboard")
        assert len(requests.received) == 2
    assert result == ExistenceResult(found=False, organization_name=None)
    assert adapter.region_of("ghostboard") is None


def test_probe_does_not_ask_eu_when_us_answers(tmp_path: Path) -> None:
    routes = {**_probe_route("us"), **_probe_route("eu")}
    with http_server(routes) as (port, requests):
        _adapter(tmp_path, port).probe(SLUG)
        assert not any(path.startswith("/eu/") for path in _paths(requests))


def test_fetch_of_an_eu_board_tries_us_then_eu_and_remembers_the_region(tmp_path: Path) -> None:
    routes = _pages("eu", [RECORDED], 100)
    with http_server(routes) as (port, requests):
        adapter = _adapter(tmp_path, port)
        fetch = adapter.fetch_board(SLUG)
        assert _paths(requests) == [
            f"/us/{SLUG}?mode=json&limit=100&skip=0",
            f"/eu/{SLUG}?mode=json&limit=100&skip=0",
        ]
    assert len(fetch.listings) == len(RECORDED)
    assert adapter.region_of(SLUG) is LeverRegion.EU


def test_a_remembered_region_sends_later_fetches_only_to_its_host(tmp_path: Path) -> None:
    routes = {**_probe_route("eu"), **_pages("eu", [RECORDED], 100)}
    with http_server(routes) as (port, requests):
        adapter = _adapter(tmp_path, port)
        adapter.probe(SLUG)
        before = len(requests.received)
        adapter.fetch_board(SLUG)
        assert _paths(requests)[before:] == [f"/eu/{SLUG}?mode=json&limit=100&skip=0"]


def test_a_board_on_neither_host_raises_board_not_found(tmp_path: Path) -> None:
    with http_server(_probe_route("us", "other")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        with pytest.raises(BoardNotFound) as caught:
            adapter.fetch_board("ghostboard")
        assert len(requests.received) == 2
    assert (caught.value.ats, caught.value.slug) == ("lever", "ghostboard")
    assert adapter.region_of("ghostboard") is None


def test_a_missing_board_is_asked_again_because_a_404_is_not_cached(tmp_path: Path) -> None:
    with http_server(_probe_route("us", "other")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        for _ in range(2):
            with pytest.raises(BoardNotFound):
                adapter.fetch_board("ghostboard")
        assert len(requests.received) == 4


def test_a_404_on_the_remembered_host_forgets_the_region(tmp_path: Path) -> None:
    with http_server(_probe_route("us")) as (port, requests):
        adapter = _adapter(tmp_path, port)
        adapter.probe(SLUG)
        before = len(requests.received)
        with pytest.raises(BoardNotFound):
            adapter.fetch_board(SLUG)
        assert _paths(requests)[before:] == [f"/us/{SLUG}?mode=json&limit=100&skip=0"]
    assert adapter.region_of(SLUG) is None


def test_a_404_on_a_later_page_raises_board_not_found_without_asking_eu(tmp_path: Path) -> None:
    routes = _pages("us", [[_posting(0), _posting(1)]], 2)
    with http_server(routes) as (port, requests), pytest.raises(BoardNotFound):
        _adapter(tmp_path, port, page_size=2).fetch_board(SLUG)
    assert _paths(requests) == [
        f"/us/{SLUG}?mode=json&limit=2&skip=0",
        f"/us/{SLUG}?mode=json&limit=2&skip=2",
    ]


def test_a_successful_fetch_of_a_us_board_remembers_us(tmp_path: Path) -> None:
    with http_server(_pages("us", [RECORDED], 100)) as (port, _):
        adapter = _adapter(tmp_path, port)
        adapter.fetch_board(SLUG)
    assert adapter.region_of(SLUG) is LeverRegion.US


def test_a_hostile_slug_cannot_change_the_path_or_query(tmp_path: Path) -> None:
    with http_server(_probe_route("us", "other")) as (port, requests), pytest.raises(BoardNotFound):
        _adapter(tmp_path, port).fetch_board("examplecoboard/../x?mode=xml#frag")
    quoted = "examplecoboard%2F..%2Fx%3Fmode%3Dxml%23frag"
    assert _paths(requests) == [
        f"/us/{quoted}?mode=json&limit=100&skip=0",
        f"/eu/{quoted}?mode=json&limit=100&skip=0",
    ]


def _refused(region: str, slug: str, status: str, page_size: int) -> dict[str, str]:
    return {f"/{region}/{slug}{_query(page_size, 0)}": status}


@pytest.mark.parametrize("status", ["403 Forbidden", "410 Gone"])
def test_a_refused_board_is_a_transport_error_not_a_missing_board(
    tmp_path: Path, status: str
) -> None:
    refusals = _refused("us", SLUG, status, 100)
    with http_server(_probe_route("eu"), refusals) as (port, requests):
        with pytest.raises(SafeHttpError) as caught:
            _adapter(tmp_path, port).fetch_board(SLUG)
        assert not any(path.startswith("/eu/") for path in _paths(requests))
    assert caught.value.reason_code == "http_status"


@pytest.mark.parametrize("status", ["403 Forbidden", "410 Gone"])
def test_probe_of_a_refused_board_is_not_reported_as_missing(tmp_path: Path, status: str) -> None:
    refusals = _refused("us", SLUG, status, 1)
    with http_server(_probe_route("eu"), refusals) as (port, requests):
        with pytest.raises(SafeHttpError) as caught:
            _adapter(tmp_path, port).probe(SLUG)
        assert not any(path.startswith("/eu/") for path in _paths(requests))
    assert caught.value.reason_code == "http_status"


def test_a_refusal_on_the_eu_host_after_a_us_404_propagates(tmp_path: Path) -> None:
    refusals = _refused("eu", SLUG, "403 Forbidden", 1)
    with http_server(_probe_route("other"), refusals) as (port, _), pytest.raises(SafeHttpError):
        _adapter(tmp_path, port).probe(SLUG)


def test_a_server_error_that_outlasts_the_retries_propagates(tmp_path: Path) -> None:
    errors = _refused("us", SLUG, "500 Internal Server Error", 100)
    with http_server(_probe_route("eu"), errors) as (port, requests):
        with pytest.raises(RetriesExhausted) as caught:
            _adapter(tmp_path, port).fetch_board(SLUG)
        assert not any(path.startswith("/eu/") for path in _paths(requests))
    assert caught.value.last_status == 500


def test_a_second_fetch_is_served_from_the_cache(tmp_path: Path) -> None:
    with http_server(_pages("us", [RECORDED], 100)) as (port, requests):
        adapter = _adapter(tmp_path, port)
        first = adapter.fetch_board(SLUG)
        second = adapter.fetch_board(SLUG)
        assert len(requests.received) == 1
    assert second == first


def test_a_seeded_region_sends_the_first_fetch_only_to_its_host(tmp_path: Path) -> None:
    with http_server(_pages("eu", [RECORDED], 100)) as (port, requests):
        adapter = _adapter(tmp_path, port)
        adapter.remember_region("ExampleCoBoard", LeverRegion.EU)
        fetch = adapter.fetch_board(SLUG)
        assert _paths(requests) == [f"/eu/{SLUG}?mode=json&limit=100&skip=0"]
    assert len(fetch.listings) == len(RECORDED)


def test_a_seeded_region_is_forgotten_when_its_host_answers_404(tmp_path: Path) -> None:
    with http_server(_pages("us", [RECORDED], 100)) as (port, requests):
        adapter = _adapter(tmp_path, port)
        adapter.remember_region(SLUG, LeverRegion.EU)
        with pytest.raises(BoardNotFound):
            adapter.fetch_board(SLUG)
        assert not any(path.startswith("/us/") for path in _paths(requests))
    assert adapter.region_of(SLUG) is None
