# ABOUTME: Tests listing state transitions (new, seen, closed) on real temp SQLite files.
# ABOUTME: A failed fetch is a real adapter failure against a loopback server, and closes nothing.
import dataclasses
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from http_support import http_server, local_target

from cypress_creek.discovery.adapters.base import (
    BoardFetch,
    BoardNotFound,
    Listing,
    ListingState,
    SkippedJob,
    SkipReason,
)
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.listings import Listings, StateChanges
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.ingest.safe_http import FetchResponse, _fetch
from cypress_creek.storage.db import connect, migrate

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def make(job_id: str, ats: str = "lever", slug: str = "acme", **overrides: object) -> Listing:
    fields: dict[str, object] = {
        "id": f"{ats}:{slug}:{job_id}",
        "ats": ats,
        "slug": slug,
        "title": "Engineer",
        "location": "Austin",
        "url": f"https://example.test/{job_id}",
        "posted_at": None,
        "fetched_at": NOW,
        "content_text": "Build things.",
        "content_hash": "abc",
    }
    fields.update(overrides)
    return Listing(**fields)  # type: ignore[arg-type]


def board(*listings: Listing, skipped: tuple[SkippedJob, ...] = ()) -> BoardFetch:
    return BoardFetch(listings=listings, skipped=skipped)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "app.sqlite3"
    with closing(connect(path)) as conn:
        migrate(conn)
    return path


@pytest.fixture
def listings(database: Path) -> Iterator[Listings]:
    conn = connect(database)
    yield Listings(conn)
    conn.close()


def states(repo: Listings, ats: str = "lever", slug: str = "acme") -> dict[str, ListingState]:
    return {item.id: item.state for item in repo.board(ats, slug)}


def test_a_first_fetch_stores_every_listing_as_new(listings: Listings) -> None:
    changes = listings.apply_fetch("lever", "acme", board(make("1"), make("2")))
    assert changes == StateChanges(added=2, seen=0, closed=0)
    assert states(listings) == {"lever:acme:1": ListingState.NEW, "lever:acme:2": ListingState.NEW}


def test_a_listing_still_present_on_the_next_fetch_becomes_seen(listings: Listings) -> None:
    listings.apply_fetch("lever", "acme", board(make("1")))
    changes = listings.apply_fetch("lever", "acme", board(make("1", title="Staff Engineer")))
    assert changes == StateChanges(added=0, seen=1, closed=0)
    (row,) = listings.board("lever", "acme")
    assert row.state is ListingState.SEEN
    assert row.title == "Staff Engineer"


def test_a_listing_absent_from_a_successful_fetch_becomes_closed(listings: Listings) -> None:
    listings.apply_fetch("lever", "acme", board(make("1"), make("2")))
    changes = listings.apply_fetch("lever", "acme", board(make("1")))
    assert changes == StateChanges(added=0, seen=1, closed=1)
    assert states(listings) == {
        "lever:acme:1": ListingState.SEEN,
        "lever:acme:2": ListingState.CLOSED,
    }


def test_a_closed_listing_that_comes_back_is_seen_again(listings: Listings) -> None:
    listings.apply_fetch("lever", "acme", board(make("1")))
    listings.apply_fetch("lever", "acme", board())
    listings.apply_fetch("lever", "acme", board(make("1")))
    assert states(listings) == {"lever:acme:1": ListingState.SEEN}


def test_an_empty_successful_fetch_closes_the_board_and_a_closed_listing_stays_closed(
    listings: Listings,
) -> None:
    listings.apply_fetch("lever", "acme", board(make("1")))
    assert listings.apply_fetch("lever", "acme", board()).closed == 1
    assert listings.apply_fetch("lever", "acme", board()).closed == 0


def test_another_board_is_never_touched(listings: Listings) -> None:
    listings.apply_fetch("lever", "acme", board(make("1")))
    listings.apply_fetch("lever", "other", board(make("9", slug="other")))
    listings.apply_fetch("lever", "acme", board())
    assert states(listings, "lever", "other") == {"lever:other:9": ListingState.NEW}


def test_a_skipped_job_with_a_known_id_is_not_closed(listings: Listings) -> None:
    listings.apply_fetch("lever", "acme", board(make("1"), make("2")))
    skipped = (SkippedJob(0, "2", "title", SkipReason.INVALID_FIELD),)
    listings.apply_fetch("lever", "acme", board(make("1"), skipped=skipped))
    assert states(listings)["lever:acme:2"] is ListingState.NEW


def test_a_skipped_job_without_an_id_closes_nothing(listings: Listings) -> None:
    listings.apply_fetch("lever", "acme", board(make("1"), make("2")))
    skipped = (SkippedJob(0, None, "id", SkipReason.INVALID_FIELD),)
    changes = listings.apply_fetch("lever", "acme", board(skipped=skipped))
    assert changes.closed == 0
    assert set(states(listings).values()) == {ListingState.NEW}


def test_a_listing_from_another_board_is_refused_and_nothing_is_written(
    listings: Listings,
) -> None:
    with pytest.raises(ValueError, match="board"):
        listings.apply_fetch("lever", "acme", board(make("1"), make("2", slug="other")))
    assert listings.board("lever", "acme") == []


def test_the_board_is_matched_after_normalizing_ats_and_slug(listings: Listings) -> None:
    listings.apply_fetch(" Lever ", "ACME ", board(make("1")))
    assert states(listings, "lever", "acme") == {"lever:acme:1": ListingState.NEW}


def test_states_persist_across_reopening_the_database(database: Path) -> None:
    with closing(connect(database)) as conn:
        Listings(conn).apply_fetch("lever", "acme", board(make("1"), make("2")))
        Listings(conn).apply_fetch("lever", "acme", board(make("1")))
    with closing(connect(database)) as reopened:
        assert states(Listings(reopened)) == {
            "lever:acme:1": ListingState.SEEN,
            "lever:acme:2": ListingState.CLOSED,
        }


def test_the_stored_row_round_trips_every_field(listings: Listings) -> None:
    original = make("1", posted_at=datetime(2025, 5, 6, tzinfo=UTC))
    listings.apply_fetch("lever", "acme", board(original))
    (row,) = listings.board("lever", "acme")
    assert row == dataclasses.replace(original, state=ListingState.NEW)


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


def _lever(tmp_path: Path, port: int) -> LeverAdapter:
    clock = ManualClock(wall_start=1_760_000_000.0)
    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LEVER_FETCH_LIMITS,
        fetch=_live_fetch,
        random_source=lambda: 0.0,
    )
    base = f"http://fixture.test:{port}"
    return LeverAdapter(client, us_base_url=f"{base}/us", eu_base_url=f"{base}/eu")


def test_a_failed_fetch_closes_nothing(listings: Listings, tmp_path: Path) -> None:
    listings.apply_fetch("lever", "acme", board(make("1"), make("2")))
    with http_server({}) as (port, requests), pytest.raises(BoardNotFound):
        listings.refresh(_lever(tmp_path, port), "lever", "acme")
    assert len(requests.received) == 2
    assert set(states(listings).values()) == {ListingState.NEW}


def test_a_successful_refresh_applies_the_fetch(listings: Listings, tmp_path: Path) -> None:
    listings.apply_fetch("lever", "acme", board(make("1")))
    with http_server({"/us/acme?mode=json&limit=100&skip=0": b"[]"}) as (port, _):
        changes = listings.refresh(_lever(tmp_path, port), "lever", "acme")
    assert changes == StateChanges(added=0, seen=0, closed=1)
