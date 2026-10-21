# ABOUTME: Runs the Ashby adapter against the real public feed through the real polite client.
# ABOUTME: Covers a real board, the probe, a made-up slug, and a real weak ETag revalidation.
import re
import time
from datetime import datetime
from pathlib import Path

import pytest

from cypress_creek.discovery.adapters.ashby import (
    ASHBY_FETCH_LIMITS,
    DEFAULT_BASE_URL,
    AshbyAdapter,
)
from cypress_creek.discovery.adapters.base import BoardFetch, BoardNotFound
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock

pytestmark = pytest.mark.needs_network

PUBLIC_BOARD = "ashby"
MISSING_BOARD = "zz-no-such-board-9f3c1b7a2e4d58061a7c3e9b5d2f4a68"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
# The shortest window that is still positive, so a second look at the board always revalidates.
EXPIRED_WINDOW_SECONDS = 0.001


def _client(cache_dir: Path, policy: FetchPolicy) -> PoliteClient:
    clock = SystemClock()
    return PoliteClient(
        policy,
        ResponseCache(cache_dir),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=ASHBY_FETCH_LIMITS,
    )


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One cache for the module, so the public board is downloaded once and then reused."""
    return tmp_path_factory.mktemp("ashby-cache") / "cache"


@pytest.fixture(scope="module")
def adapter(cache_dir: Path) -> AshbyAdapter:
    return AshbyAdapter(_client(cache_dir, FetchPolicy()))


@pytest.fixture(scope="module")
def board(adapter: AshbyAdapter) -> BoardFetch:
    return adapter.fetch_board(PUBLIC_BOARD)


def test_a_public_board_has_listings(board: BoardFetch) -> None:
    assert len(board.listings) > 0, f"skipped: {board.skipped}"


def test_a_public_board_maps_to_normalized_listings(board: BoardFetch) -> None:
    for listing in board.listings:
        assert listing.id.startswith(f"ashby:{PUBLIC_BOARD}:")
        assert listing.ats == "ashby"
        assert listing.slug == PUBLIC_BOARD
        assert listing.title.strip()
        assert listing.url.startswith("https://")
        assert listing.content_text.strip()
        assert SHA256_HEX.fullmatch(listing.content_hash)
        assert _is_aware(listing.fetched_at)
        assert listing.posted_at is not None and _is_aware(listing.posted_at)
    assert not board.skipped, f"skipped: {board.skipped}"


def test_listing_ids_are_unique(board: BoardFetch) -> None:
    ids = [listing.id for listing in board.listings]

    assert len(ids) == len(set(ids))


def test_probe_finds_a_public_board_without_an_organization_name(adapter: AshbyAdapter) -> None:
    result = adapter.probe(PUBLIC_BOARD)

    assert result.found is True
    assert result.organization_name is None


def test_probe_of_a_made_up_slug_is_not_found_and_does_not_raise(adapter: AshbyAdapter) -> None:
    result = adapter.probe(MISSING_BOARD)

    assert result.found is False
    assert result.organization_name is None


def test_fetching_a_made_up_slug_raises_board_not_found(adapter: AshbyAdapter) -> None:
    with pytest.raises(BoardNotFound) as raised:
        adapter.fetch_board(MISSING_BOARD)

    assert raised.value.reason_code == "board_not_found"
    assert raised.value.slug == MISSING_BOARD


def test_the_real_server_answers_a_weak_etag_revalidation_with_304(
    board: BoardFetch, cache_dir: Path
) -> None:
    url = f"{DEFAULT_BASE_URL}/{PUBLIC_BOARD}"
    stored = ResponseCache(cache_dir).get(url)
    assert stored is not None, "the board fixture should have stored the response"
    assert stored.etag is not None and stored.etag.startswith("W/"), f"etag: {stored.etag!r}"
    # A second client over the same cache, with a window that is already over, so that the
    # request is a real conditional request carrying the stored weak ETag.
    time.sleep(0.05)
    client = _client(cache_dir, FetchPolicy(refresh_interval_seconds=EXPIRED_WINDOW_SECONDS))

    response = client.get(url)

    assert response.status == 304, f"status: {response.status}, from_cache: {response.from_cache}"
    assert response.from_cache is True
    assert response.etag == stored.etag
    assert response.body == stored.body


def _is_aware(moment: datetime) -> bool:
    return moment.tzinfo is not None and moment.utcoffset() is not None
