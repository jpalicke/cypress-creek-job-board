# ABOUTME: Runs dedupe, filters and listing states over a real public Greenhouse board.
# ABOUTME: The board comes through the real polite client, and the states live in real SQLite.
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cypress_creek.discovery.adapters.base import BoardFetch, ListingState
from cypress_creek.discovery.adapters.greenhouse import GREENHOUSE_FETCH_LIMITS, GreenhouseAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.dedupe import dedupe
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.filters import FilterName, ListingFilters, apply_filters
from cypress_creek.discovery.listings import Listings, StateChanges
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.storage.db import connect, migrate

pytestmark = pytest.mark.needs_network

PUBLIC_BOARD = "stripe"
NO_SUCH_WORD = "zzqxjv-no-such-word-in-any-posting"


@pytest.fixture(scope="module")
def board(tmp_path_factory: pytest.TempPathFactory) -> BoardFetch:
    clock = SystemClock()
    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path_factory.mktemp("discovery-cache") / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=GREENHOUSE_FETCH_LIMITS,
    )
    return GreenhouseAdapter(client).fetch_board(PUBLIC_BOARD)


def test_a_real_board_dedupes_to_unique_ids_and_never_grows(board: BoardFetch) -> None:
    assert board.listings
    merged = dedupe(board.listings, {("greenhouse", PUBLIC_BOARD): "stripe"})
    assert len(merged) <= len(board.listings)
    ids = [item.listing.id for item in merged]
    assert len(ids) == len(set(ids))
    assert {source for item in merged for source in item.source_ids} == {
        listing.id for listing in board.listings
    }


def test_filters_over_a_real_board_count_what_they_remove(board: BoardFetch) -> None:
    today = datetime.now(UTC).date()
    nothing = apply_filters(board.listings, ListingFilters(), today)
    assert len(nothing.kept) == len(board.listings)
    everything = apply_filters(
        board.listings, ListingFilters(include_keywords=(NO_SUCH_WORD,)), today
    )
    assert everything.kept == ()
    assert everything.removed[FilterName.INCLUDE] == len(board.listings)
    assert everything.total_removed == len(board.listings)
    aged = apply_filters(board.listings, ListingFilters(max_age_days=1), date(2100, 1, 1))
    dated = sum(1 for listing in board.listings if listing.posted_at is not None)
    assert aged.removed[FilterName.AGE] == dated
    assert len(aged.kept) == len(board.listings) - dated


def test_real_listings_move_through_new_seen_and_closed(board: BoardFetch, tmp_path: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    try:
        migrate(conn)
        listings = Listings(conn)
        total = len(board.listings)
        assert listings.apply_fetch("greenhouse", PUBLIC_BOARD, board) == StateChanges(
            added=total, seen=0, closed=0
        )
        assert listings.apply_fetch("greenhouse", PUBLIC_BOARD, board) == StateChanges(
            added=0, seen=total, closed=0
        )
        half = BoardFetch(listings=board.listings[: total // 2], skipped=())
        changes = listings.apply_fetch("greenhouse", PUBLIC_BOARD, half)
        assert changes == StateChanges(added=0, seen=total // 2, closed=total - total // 2)
        states = [item.state for item in listings.board("greenhouse", PUBLIC_BOARD)]
        assert states.count(ListingState.CLOSED) == total - total // 2
    finally:
        conn.close()
