# ABOUTME: Tests the production adapter factory and the Lever region seeding from the watchlist.
# ABOUTME: The factory builds the three real adapters; nothing is fetched while it builds them.
from datetime import UTC, datetime
from pathlib import Path

from cypress_creek.discovery.adapters.ashby import AshbyAdapter
from cypress_creek.discovery.adapters.greenhouse import GreenhouseAdapter
from cypress_creek.discovery.adapters.lever import LeverAdapter, LeverRegion
from cypress_creek.discovery.factory import default_adapters, seed_lever_regions
from cypress_creek.discovery.watchlist import IdentityEvidence, WatchlistEntry

APPROVED = datetime(2026, 1, 1, tzinfo=UTC)


def test_the_factory_builds_one_real_adapter_per_supported_ats(tmp_path: Path) -> None:
    adapters = default_adapters(tmp_path / "cache")

    assert set(adapters) == {"greenhouse", "lever", "ashby"}
    assert isinstance(adapters["greenhouse"], GreenhouseAdapter)
    assert isinstance(adapters["lever"], LeverAdapter)
    assert isinstance(adapters["ashby"], AshbyAdapter)


def test_building_the_adapters_touches_no_disk_and_no_network(tmp_path: Path) -> None:
    cache = tmp_path / "cache"

    default_adapters(cache)

    assert not cache.exists()


def test_a_stored_lever_region_is_seeded_into_the_lever_adapter(tmp_path: Path) -> None:
    adapters = default_adapters(tmp_path / "cache")
    entries = [
        WatchlistEntry(
            "Euro Co", "lever", "euroco", IdentityEvidence.WEAK, APPROVED, LeverRegion.EU
        ),
        WatchlistEntry("Plain Co", "lever", "plainco", IdentityEvidence.WEAK, APPROVED),
        WatchlistEntry("Green Co", "greenhouse", "greenco", IdentityEvidence.WEAK, APPROVED),
    ]

    seed_lever_regions(adapters, entries)

    lever = adapters["lever"]
    assert isinstance(lever, LeverAdapter)
    assert lever.region_of("euroco") is LeverRegion.EU
    assert lever.region_of("plainco") is None


def test_seeding_without_a_lever_adapter_is_a_no_op() -> None:
    seed_lever_regions(
        {},
        [
            WatchlistEntry(
                "Euro Co", "lever", "euroco", IdentityEvidence.WEAK, APPROVED, LeverRegion.EU
            )
        ],
    )
