# ABOUTME: Resolves a few well known company names against the real public job boards.
# ABOUTME: Needs the internet and fails, never skips, when it is unreachable.
from pathlib import Path

import pytest

from cypress_creek.discovery.adapters.base import BoardAdapter
from cypress_creek.discovery.adapters.greenhouse import GREENHOUSE_FETCH_LIMITS, GreenhouseAdapter
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.evidence import IdentityEvidence
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.discovery.resolver import NegativeCache, Resolver

pytestmark = pytest.mark.needs_network


@pytest.fixture(scope="module")
def resolver(tmp_path_factory: pytest.TempPathFactory) -> Resolver:
    clock = SystemClock()
    root = tmp_path_factory.mktemp("resolver-cache")

    def client(name: str, limits: object) -> PoliteClient:
        return PoliteClient(
            FetchPolicy(),
            ResponseCache(root / name),
            HostRateLimiter(clock, delay_seconds=1.0),
            clock,
            limits=limits,  # type: ignore[arg-type]
        )

    adapters: dict[str, BoardAdapter] = {
        "greenhouse": GreenhouseAdapter(client("gh", GREENHOUSE_FETCH_LIMITS)),
        "lever": LeverAdapter(client("lv", LEVER_FETCH_LIMITS)),
    }
    return Resolver(adapters, NegativeCache(3600, clock.time))


def test_a_company_whose_greenhouse_board_reports_its_name_resolves_strong(
    resolver: Resolver,
) -> None:
    found = resolver.resolve("Stripe")

    assert found is not None
    assert (found.ats, found.slug) == ("greenhouse", "stripe")
    assert found.evidence is IdentityEvidence.STRONG


def test_a_company_found_only_by_slug_on_lever_resolves_weak(resolver: Resolver) -> None:
    found = resolver.resolve("Palantir")

    assert found is not None
    assert (found.ats, found.slug) == ("lever", "palantir")
    assert found.evidence is IdentityEvidence.WEAK


def test_a_made_up_company_resolves_nowhere(resolver: Resolver, tmp_path: Path) -> None:
    assert resolver.resolve("Zzyzx Quuxbar Nonexistent Holdings") is None
