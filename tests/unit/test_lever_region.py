# ABOUTME: Tests the Lever region on a watchlist entry and the adapter seed, with no database.
# ABOUTME: A region belongs to a lever board only, and a seeded slug is normalized like any other.
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter, LeverRegion
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.discovery.tombstones import InvalidBoard
from cypress_creek.discovery.watchlist import IdentityEvidence, WatchlistEntry

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def _entry(ats: str, region: LeverRegion | None) -> WatchlistEntry:
    return WatchlistEntry("Acme Corp", ats, "acme", IdentityEvidence.WEAK, NOW, region)


def _adapter(tmp_path: Path) -> LeverAdapter:
    clock = ManualClock(wall_start=1_760_000_000.0)
    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LEVER_FETCH_LIMITS,
    )
    return LeverAdapter(client)


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "workday"])
def test_a_region_on_a_board_that_is_not_lever_is_refused(ats: str) -> None:
    with pytest.raises(InvalidBoard, match="region"):
        _entry(ats, LeverRegion.US)


@pytest.mark.parametrize("region", [None, LeverRegion.US, LeverRegion.EU])
def test_a_lever_entry_accepts_no_region_or_either_region(region: LeverRegion | None) -> None:
    assert _entry(" Lever ", region).region is region


def test_a_greenhouse_entry_without_a_region_is_fine() -> None:
    assert _entry("greenhouse", None).region is None


def test_a_seeded_region_is_found_under_any_spelling_of_the_slug(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.remember_region(" ExampleCoBoard ", LeverRegion.EU)
    assert adapter.region_of("examplecoboard") is LeverRegion.EU
    assert adapter.region_of("EXAMPLECOBOARD") is LeverRegion.EU


def test_a_slug_that_was_not_seeded_has_no_region(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.remember_region("one", LeverRegion.US)
    assert adapter.region_of("two") is None


def test_seeding_again_replaces_the_region(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.remember_region("one", LeverRegion.US)
    adapter.remember_region("one", LeverRegion.EU)
    assert adapter.region_of("one") is LeverRegion.EU
