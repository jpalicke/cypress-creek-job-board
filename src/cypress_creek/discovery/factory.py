# ABOUTME: Builds the production board adapters over one polite client per ATS, and seeds regions.
# ABOUTME: Building touches no disk and no network; the first fetch creates the cache folder.
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from cypress_creek.discovery.adapters.ashby import ASHBY_FETCH_LIMITS, AshbyAdapter
from cypress_creek.discovery.adapters.ashby import ATS as ASHBY_ATS
from cypress_creek.discovery.adapters.base import BoardAdapter
from cypress_creek.discovery.adapters.greenhouse import ATS as GREENHOUSE_ATS
from cypress_creek.discovery.adapters.greenhouse import GREENHOUSE_FETCH_LIMITS, GreenhouseAdapter
from cypress_creek.discovery.adapters.lever import ATS as LEVER_ATS
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache, default_cache_dir
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.discovery.watchlist import WatchlistEntry
from cypress_creek.ingest.safe_http import FetchLimits


def _client(limits: FetchLimits, policy: FetchPolicy, cache_dir: Path) -> PoliteClient:
    clock = SystemClock()
    return PoliteClient(
        policy,
        ResponseCache(cache_dir),
        HostRateLimiter(clock, policy.per_host_delay_seconds),
        clock,
        limits=limits,
    )


def default_adapters(cache_dir: Path | None = None) -> dict[str, BoardAdapter]:
    """One real adapter for each supported ATS, each with its own polite client and limits.

    The fetch settings come from the environment (see the polite fetch settings in setup.md)."""
    folder = cache_dir if cache_dir is not None else default_cache_dir()
    policy = FetchPolicy.from_environment(os.environ)
    return {
        GREENHOUSE_ATS: GreenhouseAdapter(_client(GREENHOUSE_FETCH_LIMITS, policy, folder)),
        LEVER_ATS: LeverAdapter(_client(LEVER_FETCH_LIMITS, policy, folder)),
        ASHBY_ATS: AshbyAdapter(_client(ASHBY_FETCH_LIMITS, policy, folder)),
    }


def seed_lever_regions(
    adapters: Mapping[str, BoardAdapter], entries: Sequence[WatchlistEntry]
) -> None:
    """Tell the Lever adapter the region stored on each watchlist entry, so it asks one host."""
    lever = adapters.get(LEVER_ATS)
    if not isinstance(lever, LeverAdapter):
        return
    for entry in entries:
        if entry.ats == LEVER_ATS and entry.region is not None:
            lever.remember_region(entry.slug, entry.region)
