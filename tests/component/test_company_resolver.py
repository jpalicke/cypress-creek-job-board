# ABOUTME: Tests the company name resolver: candidate slugs, probing real adapters, evidence grades.
# ABOUTME: Real Greenhouse and Lever adapters probe a loopback server, so request headers are real.
import json
from pathlib import Path

import pytest
from http_support import Requests, http_server, local_target

from cypress_creek.discovery.adapters.base import BoardAdapter, ExistenceResult
from cypress_creek.discovery.adapters.greenhouse import GREENHOUSE_FETCH_LIMITS, GreenhouseAdapter
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.discovery.resolver import (
    NegativeCache,
    Resolver,
    candidate_slugs,
    grade_evidence,
)
from cypress_creek.discovery.watchlist import IdentityEvidence
from cypress_creek.ingest.safe_http import FetchLimits, FetchResponse, _fetch

WALL_START = 1_760_000_000.0


def _live_fetch(
    url: str, *, limits: FetchLimits, if_none_match: str | None, pass_through_statuses: bool
) -> FetchResponse:
    return _fetch(
        url,
        limits,
        resolve=local_target,
        if_none_match=if_none_match,
        pass_through_statuses=pass_through_statuses,
    )


def _client(tmp_path: Path, name: str, limits: FetchLimits, clock: ManualClock) -> PoliteClient:
    return PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / name),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=limits,
        fetch=_live_fetch,
        random_source=lambda: 0.0,
    )


def _adapters(tmp_path: Path, port: int, clock: ManualClock) -> dict[str, BoardAdapter]:
    base = f"http://fixture.test:{port}"
    return {
        "greenhouse": GreenhouseAdapter(
            _client(tmp_path, "gh", GREENHOUSE_FETCH_LIMITS, clock), base_url=base
        ),
        "lever": LeverAdapter(
            _client(tmp_path, "lv", LEVER_FETCH_LIMITS, clock),
            us_base_url=f"{base}/lever",
            eu_base_url=f"{base}/lever-eu",
        ),
    }


def _board(name: str) -> bytes:
    return json.dumps({"name": name, "content": ""}).encode("utf-8")


def _lever_page() -> bytes:
    return b"[]"


def _paths(requests: Requests) -> list[str]:
    return [path for path, _ in requests.received]


@pytest.mark.parametrize(
    ("name", "slugs"),
    [
        ("Example Co", ["example-co", "exampleco", "example"]),
        ("Acme Corporation", ["acme"]),
        ("Globex", ["globex"]),
        ("O'Reilly Media", ["oreilly-media", "oreillymedia", "oreilly"]),
        ("Café Noir Inc.", ["cafe-noir", "cafenoir", "cafe"]),
    ],
)
def test_candidate_slugs_are_a_few_plain_lowercase_forms_of_the_name(
    name: str, slugs: list[str]
) -> None:
    assert candidate_slugs(name) == slugs


def test_a_name_with_no_ascii_letters_has_no_candidate_slug() -> None:
    assert candidate_slugs("株式会社") == []


def test_every_candidate_slug_is_a_safe_board_name() -> None:
    for name in ["Example Co", "A B C D E F G H", "x" * 60, "Dr. Who & Sons, Ltd"]:
        for slug in candidate_slugs(name):
            assert slug.replace("-", "").isalnum() and slug == slug.lower() and slug.isascii()
            assert 2 <= len(slug) <= 63


@pytest.mark.parametrize(
    ("name", "result", "grade"),
    [
        ("Example Co", ExistenceResult(True, "Example Co"), IdentityEvidence.STRONG),
        ("Example Co", ExistenceResult(True, "EXAMPLE CO INC."), IdentityEvidence.STRONG),
        ("Example Co", ExistenceResult(True, None), IdentityEvidence.WEAK),
        ("Example Co", ExistenceResult(True, "Totally Different Ltd"), IdentityEvidence.NONE),
        ("Example Co", ExistenceResult(False, None), IdentityEvidence.NONE),
    ],
)
def test_evidence_is_strong_for_a_matching_name_weak_for_a_slug_only_and_none_otherwise(
    name: str, result: ExistenceResult, grade: IdentityEvidence
) -> None:
    assert grade_evidence(name, result) is grade


def test_a_greenhouse_org_name_match_is_strong_and_a_lever_slug_is_weak(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=WALL_START)
    routes = {
        "/v1/boards/exampleco": _board("Example Co"),
        "/lever/globex?mode=json&limit=1&skip=0": _lever_page(),
    }
    with http_server(routes) as (port, _):
        resolver = Resolver(_adapters(tmp_path, port, clock), NegativeCache(3600, clock.time))
        strong = resolver.resolve("Example Co")
        weak = resolver.resolve("Globex")
        nowhere = resolver.resolve("Initech")

    assert strong is not None and (strong.ats, strong.slug) == ("greenhouse", "exampleco")
    assert strong.evidence is IdentityEvidence.STRONG
    assert strong.organization_name == "Example Co"
    assert weak is not None and (weak.ats, weak.slug) == ("lever", "globex")
    assert weak.evidence is IdentityEvidence.WEAK
    assert nowhere is None


def test_a_board_that_belongs_to_a_different_company_is_dropped(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=WALL_START)
    with http_server({"/v1/boards/globex": _board("Hooli")}) as (port, _):
        resolver = Resolver(_adapters(tmp_path, port, clock), NegativeCache(3600, clock.time))
        assert resolver.resolve("Globex") is None


def test_the_strongest_evidence_wins_over_an_earlier_weak_one(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=WALL_START)
    routes = {
        "/lever/exampleco?mode=json&limit=1&skip=0": _lever_page(),
        "/v1/boards/exampleco": _board("Example Co"),
    }
    with http_server(routes) as (port, _):
        adapters = _adapters(tmp_path, port, clock)
        reversed_order = {"lever": adapters["lever"], "greenhouse": adapters["greenhouse"]}
        found = Resolver(reversed_order, NegativeCache(3600, clock.time)).resolve("Example Co")

    assert found is not None and found.ats == "greenhouse"


def test_requests_carry_the_honest_user_agent(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=WALL_START)
    with http_server({"/v1/boards/globex": _board("Globex")}) as (port, requests):
        Resolver(_adapters(tmp_path, port, clock), NegativeCache(3600, clock.time)).resolve(
            "Globex"
        )

    assert requests.received
    for _, headers in requests.received:
        assert headers["user-agent"].startswith("cypress-creek/")


def test_a_missing_board_is_remembered_so_it_is_not_asked_again_until_it_expires(
    tmp_path: Path,
) -> None:
    clock = ManualClock(wall_start=WALL_START)
    with http_server({}) as (port, requests):
        resolver = Resolver(_adapters(tmp_path, port, clock), NegativeCache(600, clock.time))
        assert resolver.resolve("Initech") is None
        first = len(requests.received)
        assert resolver.resolve("Initech") is None
        assert len(requests.received) == first
        clock.advance(601)
        assert resolver.resolve("Initech") is None
        assert len(requests.received) > first


def test_a_transient_failure_is_not_remembered_as_missing(tmp_path: Path) -> None:
    clock = ManualClock(wall_start=WALL_START)
    cache = NegativeCache(600, clock.time)
    with http_server({}, {"/v1/boards/initech": "403 Forbidden"}) as (port, requests):
        resolver = Resolver(_adapters(tmp_path, port, clock), cache)
        assert resolver.resolve("Initech") is None
        assert resolver.last_errors
        assert not cache.is_missing("greenhouse", "initech")
        assert cache.is_missing("lever", "initech")
    assert "/v1/boards/initech" in _paths(requests)
