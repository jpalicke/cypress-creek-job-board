# ABOUTME: Runs the Lever adapter against the real public feed through the real polite client.
# ABOUTME: Covers a paged US board, the probe, a made-up slug, and a board on the EU host.
import re
from datetime import datetime

import pytest

from cypress_creek.discovery.adapters.base import BoardFetch, BoardNotFound
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter, LeverRegion
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.ingest.safe_http import FetchLimits, FetchResponse, fetch_url

pytestmark = pytest.mark.needs_network

LARGE_PUBLIC_BOARD = "palantir"
# A board that lives only on api.eu.lever.co. It answered 200 there and 404 on the US host on
# 2026-10-14, with no open postings at that time, so only its existence and region are asserted.
EU_ONLY_BOARD = "kaiko"
MISSING_BOARD = "zz-no-such-board-9f3c1b7a2e4d58061a7c3e9b5d2f4a68"
SMALL_PAGE = 10
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _adapter(cache_dir_parent: pytest.TempPathFactory, name: str, page_size: int) -> LeverAdapter:
    clock = SystemClock()
    cache = ResponseCache(cache_dir_parent.mktemp(name) / "cache")
    client = PoliteClient(
        FetchPolicy(),
        cache,
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LEVER_FETCH_LIMITS,
    )
    return LeverAdapter(client, page_size=page_size)


@pytest.fixture(scope="module")
def adapter(tmp_path_factory: pytest.TempPathFactory) -> LeverAdapter:
    """One adapter and one cache for the module, so each board is downloaded once."""
    return _adapter(tmp_path_factory, "lever-cache", SMALL_PAGE)


@pytest.fixture(scope="module")
def board(adapter: LeverAdapter) -> BoardFetch:
    return adapter.fetch_board(LARGE_PUBLIC_BOARD)


def test_a_large_board_is_read_across_several_pages(board: BoardFetch) -> None:
    assert len(board.listings) > SMALL_PAGE, f"skipped: {board.skipped}"


def test_a_large_board_maps_to_normalized_listings(board: BoardFetch) -> None:
    for listing in board.listings:
        assert listing.id.startswith(f"lever:{LARGE_PUBLIC_BOARD}:")
        assert listing.ats == "lever"
        assert listing.slug == LARGE_PUBLIC_BOARD
        assert listing.title.strip()
        assert listing.url.startswith("https://")
        assert listing.content_text.strip()
        assert SHA256_HEX.fullmatch(listing.content_hash)
        assert listing.fetched_at.tzinfo is not None
        assert listing.posted_at is not None and _is_aware(listing.posted_at)
    assert not board.skipped, f"skipped: {board.skipped}"


def test_listing_ids_are_unique_across_pages(board: BoardFetch) -> None:
    ids = [listing.id for listing in board.listings]

    assert len(ids) == len(set(ids))


def test_probe_finds_a_us_board_without_an_organization_name(adapter: LeverAdapter) -> None:
    result = adapter.probe(LARGE_PUBLIC_BOARD)

    assert result.found is True
    assert result.organization_name is None
    assert adapter.region_of(LARGE_PUBLIC_BOARD) is LeverRegion.US


def test_probe_of_a_made_up_slug_is_not_found_and_does_not_raise(adapter: LeverAdapter) -> None:
    result = adapter.probe(MISSING_BOARD)

    assert result.found is False
    assert result.organization_name is None
    assert adapter.region_of(MISSING_BOARD) is None


def test_fetching_a_made_up_slug_raises_board_not_found(adapter: LeverAdapter) -> None:
    with pytest.raises(BoardNotFound) as raised:
        adapter.fetch_board(MISSING_BOARD)

    assert raised.value.reason_code == "board_not_found"
    assert raised.value.slug == MISSING_BOARD


def test_a_board_on_the_eu_host_is_found_there_after_the_us_host_says_404(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    eu_adapter = _adapter(tmp_path_factory, "lever-eu-cache", SMALL_PAGE)

    result = eu_adapter.probe(EU_ONLY_BOARD)
    fetched = eu_adapter.fetch_board(EU_ONLY_BOARD)

    assert result.found is True
    assert result.organization_name is None
    assert eu_adapter.region_of(EU_ONLY_BOARD) is LeverRegion.EU
    assert not fetched.skipped, f"skipped: {fetched.skipped}"


def _is_aware(moment: datetime) -> bool:
    return moment.tzinfo is not None and moment.utcoffset() is not None


class _RecordingFetch:
    """The real fetch, with each requested URL noted so a test can see which host was asked."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(
        self,
        url: str,
        *,
        limits: FetchLimits,
        if_none_match: str | None,
        pass_through_statuses: bool,
    ) -> FetchResponse:
        self.urls.append(url)
        return fetch_url(
            url,
            limits=limits,
            if_none_match=if_none_match,
            pass_through_statuses=pass_through_statuses,
        )


def test_a_seeded_eu_region_reaches_the_eu_host_without_asking_the_us_host(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    clock = SystemClock()
    recorder = _RecordingFetch()
    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path_factory.mktemp("lever-seeded-cache") / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LEVER_FETCH_LIMITS,
        fetch=recorder,
    )
    seeded = LeverAdapter(client, page_size=SMALL_PAGE)
    seeded.remember_region(EU_ONLY_BOARD, LeverRegion.EU)

    fetched = seeded.fetch_board(EU_ONLY_BOARD)

    assert not fetched.skipped, f"skipped: {fetched.skipped}"
    assert recorder.urls, "the real client made no request"
    assert all(url.startswith("https://api.eu.lever.co/") for url in recorder.urls), recorder.urls
    assert seeded.region_of(EU_ONLY_BOARD) is LeverRegion.EU
