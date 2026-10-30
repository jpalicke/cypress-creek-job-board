# ABOUTME: Tests the discovery run: cap, content hash cache, blacklist, ranking and backend failure.
# ABOUTME: Real adapters fetch from loopback servers, state is in SQLite, the model is unreachable.
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from discovery_support import (
    BACKEND,
    BANK,
    MODEL,
    NOW,
    SLUG,
    TODAY,
    Scorer,
    extraction,
    lever_adapter,
    lever_routes,
    no_sleep,
    provider,
)
from http_support import http_server

from cypress_creek.discovery.adapters.lever import LeverAdapter
from cypress_creek.discovery.blacklist import BlacklistEntry, BlockReason
from cypress_creek.discovery.filters import FilterName, ListingFilters
from cypress_creek.discovery.run import (
    RankedListing,
    RunIdentity,
    ScoreStatus,
    posting_from_listing,
    ranked_listings,
    run_discovery,
)
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import (
    Posting,
)
from cypress_creek.pipeline.extract import ExtractionStatus
from cypress_creek.pipeline.report import GapReport
from cypress_creek.pipeline.run import analyze, assess
from cypress_creek.pipeline.version import pipeline_version
from cypress_creek.providers import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.storage.company_key import company_key
from cypress_creek.storage.db import connect, migrate


@pytest.fixture
def bank(tmp_path: Path) -> Bank:
    path = tmp_path / "bank.yaml"
    path.write_text(BANK, encoding="utf8")
    return load_bank(path)


@pytest.fixture
def identity(bank: Bank) -> RunIdentity:
    return RunIdentity(bank_digest=bank_hash(bank), backend=BACKEND, model=MODEL)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    connection = connect(tmp_path / "app.sqlite3")
    migrate(connection)
    Watchlist(connection).add(
        WatchlistEntry("Example Co", "lever", SLUG, IdentityEvidence.WEAK, NOW)
    )
    yield connection
    connection.close()


def _run(
    conn: Any,
    adapter: LeverAdapter,
    scorer: Callable[[Posting], GapReport],
    identity: RunIdentity,
    cap: int = 30,
    blacklist: list[BlacklistEntry] | None = None,
    filters: ListingFilters | None = None,
) -> Any:
    return run_discovery(
        conn,
        {"lever": adapter},
        blacklist or [],
        filters or ListingFilters(),
        scorer,
        identity,
        cap=cap,
        today=TODAY,
        now=NOW,
    )


def test_a_run_stops_at_the_cap_and_reports_what_remains(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(50)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), scorer, identity, cap=30)
    assert len(scorer.calls) == 30
    assert result.summary.fetched == 50
    assert result.summary.scored == 30
    assert result.summary.unscored == 20
    assert result.summary.stopped_by == "cap"
    statuses = [item.status for item in result.ranked]
    assert statuses.count(ScoreStatus.SCORED) == 30
    assert statuses.count(ScoreStatus.UNSCORED) == 20
    assert len(result.ranked) == 50


def test_every_analyzer_call_counts_against_the_cap_even_when_extraction_fails(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    calls: list[str] = []

    def always_a_schema_violation(posting: Posting) -> GapReport:
        calls.append(posting.id)
        failed = extraction(["kubernetes"]).model_copy(
            update={
                "status": ExtractionStatus.INCOMPLETE,
                "requirements": [],
                "failure": "schema_violation",
                "usage": None,
            }
        )
        return assess(
            posting,
            failed,
            bank,
            provider(),
            backend=BACKEND,
            model=MODEL,
            today=TODAY,
            sleep=no_sleep,
        )

    with http_server(lever_routes(10)) as (port, _):
        result = _run(
            conn, lever_adapter(tmp_path, port), always_a_schema_violation, identity, cap=3
        )
    assert len(calls) == 3
    assert result.summary.stopped_by == "cap"
    assert result.summary.scored == 0
    assert result.summary.unscored == 10


def test_the_cap_scores_the_most_recent_listings_first(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(10)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), scorer, identity, cap=3)
    scored = {item.listing.id for item in result.ranked if item.status is ScoreStatus.SCORED}
    assert scored == {f"lever:{SLUG}:posting-{n}" for n in (9, 8, 7)}


def test_a_second_run_on_unchanged_listings_makes_no_model_calls(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(5)) as (port, _):
        first = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
        again = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
    assert first.summary.scored == 5
    assert len(scorer.calls) == 5
    assert again.summary.scored == 0
    assert again.summary.cache_hits == 5
    assert [item.run_id for item in again.ranked] == [item.run_id for item in first.ranked]


def test_an_incomplete_score_is_shown_with_a_flag_and_tried_again_next_run(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    # "python" has a candidate fact, so entailment runs, and the model cannot answer.
    scorer = Scorer(bank, terms=["python"])
    with http_server(lever_routes(2)) as (port, _):
        first = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
        again = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
    assert {item.incomplete for item in first.ranked} == {True}
    assert {item.status for item in first.ranked} == {ScoreStatus.SCORED}
    assert again.summary.cache_hits == 0
    assert again.summary.scored == 2
    assert len(scorer.calls) == 4


def test_a_changed_description_is_rescored(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(3)) as (port, _):
        _run(conn, lever_adapter(tmp_path, port), scorer, identity)
    with http_server(lever_routes(3, note="Now with a new paragraph.")) as (port, _):
        again = _run(conn, lever_adapter(tmp_path / "second", port), scorer, identity)
    assert again.summary.scored == 3
    assert again.summary.cache_hits == 0
    assert len(scorer.calls) == 6


def test_a_changed_listing_shows_as_unscored_until_it_is_scored_again(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(3)) as (port, _):
        _run(conn, lever_adapter(tmp_path, port), scorer, identity)
    with http_server(lever_routes(3, note="Now with a new paragraph.")) as (port, _):
        held = _run(conn, lever_adapter(tmp_path / "second", port), scorer, identity, cap=0)
    assert {item.status for item in held.ranked} == {ScoreStatus.UNSCORED}
    assert held.summary.stopped_by == "cap"
    assert len(scorer.calls) == 3


def test_a_new_pipeline_version_rescored_everything(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(3)) as (port, _):
        first = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
        newer = RunIdentity(
            identity.bank_digest, identity.backend, identity.model, pipeline_version="f" * 64
        )
        again = _run(conn, lever_adapter(tmp_path, port), scorer, newer)
    assert first.summary.scored == 3
    assert again.summary.cache_hits == 0
    assert again.summary.scored == 3
    assert len(scorer.calls) == 6


def test_the_default_identity_carries_the_current_pipeline_version(identity: RunIdentity) -> None:
    assert identity.pipeline_version == pipeline_version()


def test_a_changed_bank_or_model_is_rescored(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(2)) as (port, _):
        _run(conn, lever_adapter(tmp_path, port), scorer, identity)
        other = RunIdentity(identity.bank_digest, identity.backend, "another-model")
        again = _run(conn, lever_adapter(tmp_path, port), scorer, other)
    assert again.summary.scored == 2


def test_a_blacklisted_company_is_never_fetched_or_scored(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    blocked = [BlacklistEntry(BlockReason.COMPANY_KEY, "Example Co", "not a fit", NOW)]
    with http_server(lever_routes(5)) as (port, requests):
        result = _run(conn, lever_adapter(tmp_path, port), scorer, identity, blacklist=blocked)
    assert requests.received == []
    assert scorer.calls == []
    assert result.summary.blocked_boards == 1
    assert result.ranked == ()


def test_stored_listings_of_a_blacklisted_company_are_not_ranked(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(3)) as (port, _):
        _run(conn, lever_adapter(tmp_path, port), scorer, identity)
        blocked = [BlacklistEntry(BlockReason.SLUG, SLUG, "not a fit", NOW)]
        later = _run(conn, lever_adapter(tmp_path, port), scorer, identity, blacklist=blocked)
    assert later.ranked == ()


def test_filters_run_before_scoring_and_are_counted(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    filters = ListingFilters(include_keywords=("unit 1",))
    with http_server(lever_routes(12)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), scorer, identity, filters=filters)
    # Matching is on whole words, so "unit 1" does not match "unit 10".
    assert scorer.calls == [f"lever:{SLUG}:posting-1"]
    assert result.summary.filtered_out[FilterName.INCLUDE] == 11


def test_zero_requirements_show_no_score_and_sort_below_scored_rows(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    class Mixed(Scorer):
        def __call__(self, posting: Posting) -> GapReport:
            self.terms = [] if posting.id.endswith("posting-2") else ["kubernetes"]
            return super().__call__(posting)

    with http_server(lever_routes(3)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), Mixed(bank), identity)
    assert [item.status for item in result.ranked] == [
        ScoreStatus.SCORED,
        ScoreStatus.SCORED,
        ScoreStatus.NO_SCORE,
    ]
    assert result.ranked[-1].listing.id.endswith("posting-2")
    assert result.ranked[-1].score is None


def test_the_backend_going_down_halfway_keeps_scored_rows_and_marks_the_rest_unscored(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    working = Scorer(bank)

    def failing_after_two(posting: Posting) -> GapReport:
        if len(working.calls) < 2:
            return working(posting)
        return analyze(
            posting,
            bank,
            provider(),
            backend=BACKEND,
            model=MODEL,
            today=TODAY,
            sleep=no_sleep,
        )

    with http_server(lever_routes(6)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), failing_after_two, identity)
    statuses = [item.status for item in result.ranked]
    assert statuses.count(ScoreStatus.SCORED) == 2
    assert statuses.count(ScoreStatus.UNSCORED) == 4
    assert result.summary.stopped_by == "backend"
    assert result.summary.scored == 2
    assert result.summary.unscored == 4


def test_an_exhausted_budget_stops_scoring_and_reports_what_was_left(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    inner = provider()
    tracker = BudgetTracker(Budget(max_input_tokens=1), inner.capabilities.cost_per_mtok)
    budgeted = BudgetedProvider(inner, tracker)

    def over_budget(posting: Posting) -> GapReport:
        return analyze(
            posting,
            bank,
            budgeted,
            backend=BACKEND,
            model=MODEL,
            today=TODAY,
            sleep=no_sleep,
        )

    with http_server(lever_routes(4)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), over_budget, identity)
    assert result.summary.stopped_by == "budget"
    assert result.summary.scored == 0
    assert result.summary.unscored == 4
    assert {item.status for item in result.ranked} == {ScoreStatus.UNSCORED}


def test_a_failed_board_fetch_is_reported_and_other_boards_still_run(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    Watchlist(conn).add(WatchlistEntry("Ghost Inc", "lever", "ghost", IdentityEvidence.WEAK, NOW))
    scorer = Scorer(bank)
    with http_server(lever_routes(3)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
    assert [(error.ats, error.slug, error.reason) for error in result.summary.errors] == [
        ("lever", "ghost", "BoardNotFound")
    ]
    assert result.summary.scored == 3


def test_a_listing_is_scored_as_a_posting_with_its_stored_text(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    seen: list[Posting] = []
    scorer = Scorer(bank)

    def recording(posting: Posting) -> GapReport:
        seen.append(posting)
        return scorer(posting)

    with http_server(lever_routes(1)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), recording, identity)
    (ranked,) = result.ranked
    assert seen == [posting_from_listing(ranked.listing)]


def test_the_ranked_list_can_be_read_back_without_a_run(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(4)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
    boards = {("lever", SLUG): company_key("Example Co")}
    again: list[RankedListing] = ranked_listings(conn, boards, ListingFilters(), identity, TODAY)
    assert again == list(result.ranked)


def test_each_scored_row_links_to_a_stored_gap_report(
    conn: Any, tmp_path: Path, bank: Bank, identity: RunIdentity
) -> None:
    scorer = Scorer(bank)
    with http_server(lever_routes(2)) as (port, _):
        result = _run(conn, lever_adapter(tmp_path, port), scorer, identity)
    for item in result.ranked:
        assert item.run_id is not None
        (stored,) = conn.execute(
            "SELECT report_json FROM discovery_report WHERE run_id = ?", (item.run_id,)
        ).fetchone()
        assert GapReport.model_validate_json(stored).provenance.run_id == item.run_id
