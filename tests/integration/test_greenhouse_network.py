# ABOUTME: Runs the Greenhouse adapter against a large public board through the real polite client.
# ABOUTME: Covers a full board fetch, the board probe, and a made-up slug for both operations.
import re
from datetime import datetime

import pytest

from cypress_creek.discovery.adapters.base import (
    MAX_SKIPPED_FRACTION,
    BoardFetch,
    BoardNotFound,
    ListingState,
)
from cypress_creek.discovery.adapters.greenhouse import GREENHOUSE_FETCH_LIMITS, GreenhouseAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock

pytestmark = pytest.mark.needs_network

LARGE_PUBLIC_BOARD = "stripe"
MISSING_BOARD = "zz-no-such-board-h3-probe"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


@pytest.fixture(scope="module")
def adapter(tmp_path_factory: pytest.TempPathFactory) -> GreenhouseAdapter:
    """One adapter and one cache for the module, so the large board is downloaded once."""
    clock = SystemClock()
    cache = ResponseCache(tmp_path_factory.mktemp("greenhouse-cache") / "cache")
    client = PoliteClient(
        FetchPolicy(),
        cache,
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=GREENHOUSE_FETCH_LIMITS,
    )
    return GreenhouseAdapter(client)


@pytest.fixture(scope="module")
def board(adapter: GreenhouseAdapter) -> BoardFetch:
    return adapter.fetch_board(LARGE_PUBLIC_BOARD)


def test_a_large_public_board_maps_to_normalized_listings(board: BoardFetch) -> None:
    assert board.listings
    for listing in board.listings:
        assert listing.id.startswith(f"greenhouse:{LARGE_PUBLIC_BOARD}:")
        assert listing.ats == "greenhouse"
        assert listing.slug == LARGE_PUBLIC_BOARD
        assert listing.title.strip()
        assert listing.url.startswith("https://")
        assert listing.content_text.strip()
        assert SHA256_HEX.fullmatch(listing.content_hash)
        assert listing.state is ListingState.NEW
        assert listing.fetched_at.tzinfo is not None
        assert listing.posted_at is None or _is_aware(listing.posted_at)


def test_a_real_board_stays_within_the_skip_budget(board: BoardFetch) -> None:
    total = len(board.listings) + len(board.skipped)

    assert len(board.skipped) <= total * MAX_SKIPPED_FRACTION


def test_listing_ids_are_unique_on_a_real_board(board: BoardFetch) -> None:
    ids = [listing.id for listing in board.listings]

    assert len(ids) == len(set(ids))


def test_probe_finds_a_real_board_and_reports_its_organization(
    adapter: GreenhouseAdapter,
) -> None:
    result = adapter.probe(LARGE_PUBLIC_BOARD)

    assert result.found is True
    assert result.organization_name
    assert result.organization_name.strip() == result.organization_name


def test_probe_of_a_made_up_slug_is_not_found_and_does_not_raise(
    adapter: GreenhouseAdapter,
) -> None:
    result = adapter.probe(MISSING_BOARD)

    assert result.found is False
    assert result.organization_name is None


def test_fetching_a_made_up_slug_raises_board_not_found(adapter: GreenhouseAdapter) -> None:
    with pytest.raises(BoardNotFound) as raised:
        adapter.fetch_board(MISSING_BOARD)

    assert raised.value.reason_code == "board_not_found"
    assert raised.value.slug == MISSING_BOARD


def _is_aware(moment: datetime) -> bool:
    return moment.tzinfo is not None and moment.utcoffset() is not None
