# ABOUTME: One discovery run: fetch the watchlist, dedupe, filter, score under a cap, then rank.
# ABOUTME: Scores are cached by run id, so an unchanged listing is never scored again.
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from cypress_creek.discovery.adapters.base import BoardAdapter, Listing, ListingState
from cypress_creek.discovery.blacklist import BlacklistEntry, Candidate, is_blacklisted
from cypress_creek.discovery.dedupe import MergedListing, dedupe
from cypress_creek.discovery.filters import FilterName, ListingFilters, apply_filters
from cypress_creek.discovery.listings import Listings
from cypress_creek.discovery.tombstones import normalize_board
from cypress_creek.discovery.watchlist import Watchlist
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.pipeline.report import GapReport, ReportStatus
from cypress_creek.pipeline.run import run_id
from cypress_creek.pipeline.version import pipeline_version
from cypress_creek.providers.errors import BudgetExceeded
from cypress_creek.scoring.support import Support

DEFAULT_CAP = 30
# Failures that mean the backend cannot answer right now. Scoring stops instead of trying every
# remaining listing against a backend that is down.
_BACKEND_DOWN = ("provider_unavailable", "rate_limited")
_EXTRACTION_FAILED = "extraction failed: "

Analyzer = Callable[[Posting], GapReport]


class ScoreStatus(StrEnum):
    SCORED = "scored"
    NO_SCORE = "no_score"
    UNSCORED = "unscored"


@dataclass(frozen=True)
class RunIdentity:
    """What a cached score depends on besides the listing text.

    The pipeline version is a digest of the prompts, stages, validators, scoring and config, so a
    score judged by older code is never reused."""

    bank_digest: str
    backend: str
    model: str
    pipeline_version: str = field(default_factory=pipeline_version)


@dataclass(frozen=True)
class RankedListing:
    """One row of the ranked list. The score is for triage only, not a probability."""

    listing: Listing
    urls: tuple[str, ...]
    status: ScoreStatus
    score: float | None
    strong: int
    partial: int
    none: int
    incomplete: bool
    run_id: str | None


@dataclass(frozen=True)
class BoardError:
    """A board that could not be fetched. The reason is the error type, never feed text."""

    ats: str
    slug: str
    reason: str


@dataclass(frozen=True)
class RunSummary:
    """What a run did. stopped_by is cap, budget, backend or None."""

    fetched: int
    blocked_boards: int
    filtered_out: dict[FilterName, int]
    scored: int
    cache_hits: int
    unscored: int
    stopped_by: str | None
    errors: tuple[BoardError, ...]


@dataclass(frozen=True)
class DiscoveryResult:
    ranked: tuple[RankedListing, ...]
    summary: RunSummary


def posting_from_listing(listing: Listing) -> Posting:
    """A listing is scored as a feed posting, with exactly the stored text."""
    return Posting(
        id=listing.id,
        source=PostingSource.FEED,
        text=listing.content_text,
        text_hash=text_hash(listing.content_text),
        origin_url=listing.url,
        extractor=Extractor(name=listing.ats, version="1"),
        created_at=listing.fetched_at,
    )


def rank(rows: Iterable[RankedListing]) -> list[RankedListing]:
    """Scored rows by score then recency, then rows with no score, then unscored rows."""
    order = {ScoreStatus.SCORED: 0, ScoreStatus.NO_SCORE: 1, ScoreStatus.UNSCORED: 2}

    def key(row: RankedListing) -> tuple[int, float, float, str]:
        posted = row.listing.posted_at
        return (
            order[row.status],
            -(row.score or 0.0),
            -(posted.timestamp() if posted else float("-inf")),
            row.listing.id,
        )

    return sorted(rows, key=key)


def run_discovery(
    conn: sqlite3.Connection,
    adapters: Mapping[str, BoardAdapter],
    blacklist: Sequence[BlacklistEntry],
    filters: ListingFilters,
    analyzer: Analyzer,
    identity: RunIdentity,
    *,
    cap: int = DEFAULT_CAP,
    today: date,
    now: datetime,
) -> DiscoveryResult:
    """Refresh every watched board that is not blacklisted, then score what survives.

    A blacklisted board is never fetched. A board that fails is reported and the others still
    run. At most `cap` listings are sent to the analyzer, most recent first, and a stored score
    for the same text, bank, backend and model is reused for free. Scoring stops when the
    backend cannot answer or the budget is exhausted, and everything left is shown unscored."""
    if cap < 0:
        raise ValueError("the cap cannot be negative")
    listings = Listings(conn)
    boards: dict[tuple[str, str], str] = {}
    errors: list[BoardError] = []
    blocked = 0
    fetched = 0
    for entry in Watchlist(conn).entries():
        if is_blacklisted(Candidate(entry.display_name, entry.slug, None), blacklist):
            blocked += 1
            continue
        boards[(entry.ats, entry.slug)] = entry.company_key
        adapter = adapters.get(entry.ats)
        if adapter is None:
            errors.append(BoardError(entry.ats, entry.slug, "NoAdapter"))
            continue
        try:
            fetch = adapter.fetch_board(entry.slug)
        except Exception as error:  # noqa: BLE001 - any fetch failure is reported, never raised
            errors.append(BoardError(entry.ats, entry.slug, type(error).__name__))
            continue
        listings.apply_fetch(entry.ats, entry.slug, fetch)
        fetched += len(fetch.listings)
    candidates = _candidates(conn, boards, filters, today)
    scored = hits = calls = 0
    stopped_by: str | None = None
    for merged in sorted(candidates.kept, key=_newest_first):
        listing = merged.listing
        key = run_id(
            text_hash(listing.content_text), identity.bank_digest, identity.backend, identity.model
        )
        stored = _load_report(conn, key, identity.pipeline_version)
        if stored is not None and stored.status is ReportStatus.COMPLETE:
            hits += 1
            continue
        if stopped_by is not None:
            continue
        if calls >= cap:
            stopped_by = "cap"
            continue
        calls += 1
        try:
            report = analyzer(posting_from_listing(listing))
        except BudgetExceeded:
            stopped_by = "budget"
            continue
        failure = _extraction_failure(report)
        if failure is not None:
            if failure in _BACKEND_DOWN:
                stopped_by = "backend"
            continue
        _store(conn, key, identity.pipeline_version, listing.content_hash, report, now)
        scored += 1
    ranked = ranked_listings(conn, boards, filters, identity, today)
    unscored = sum(1 for row in ranked if row.status is ScoreStatus.UNSCORED)
    summary = RunSummary(
        fetched=fetched,
        blocked_boards=blocked,
        filtered_out=candidates.removed,
        scored=scored,
        cache_hits=hits,
        unscored=unscored,
        stopped_by=stopped_by,
        errors=tuple(errors),
    )
    return DiscoveryResult(ranked=tuple(ranked), summary=summary)


def ranked_listings(
    conn: sqlite3.Connection,
    boards: Mapping[tuple[str, str], str],
    filters: ListingFilters,
    identity: RunIdentity,
    today: date,
) -> list[RankedListing]:
    """The ranked list from what is stored: open listings of the given boards, deduped, filtered.

    A stored score is found by the run id, which covers the listing text, the bank, the backend and
    the model, so a changed listing, bank or model shows as unscored until it is scored again."""
    candidates = _candidates(conn, boards, filters, today)
    rows = []
    for merged in candidates.kept:
        listing = merged.listing
        key = run_id(
            text_hash(listing.content_text), identity.bank_digest, identity.backend, identity.model
        )
        rows.append(_row(merged, key, _load_report(conn, key, identity.pipeline_version)))
    return rank(rows)


@dataclass(frozen=True)
class _Candidates:
    kept: list[MergedListing]
    removed: dict[FilterName, int]


def _candidates(
    conn: sqlite3.Connection,
    boards: Mapping[tuple[str, str], str],
    filters: ListingFilters,
    today: date,
) -> _Candidates:
    stored: list[Listing] = []
    listings = Listings(conn)
    for ats, slug in boards:
        stored.extend(
            item for item in listings.board(ats, slug) if item.state is not ListingState.CLOSED
        )
    normalized = {normalize_board(*board): key for board, key in boards.items()}
    merged = dedupe(stored, normalized)
    report = apply_filters([item.listing for item in merged], filters, today)
    keep = {item.id for item in report.kept}
    by_listing: dict[str, MergedListing] = {item.listing.id: item for item in merged}
    return _Candidates(
        kept=[by_listing[listing_id] for listing_id in sorted(keep)],
        removed=report.removed,
    )


def _newest_first(merged: MergedListing) -> tuple[float, str]:
    posted = merged.listing.posted_at
    return (-(posted.timestamp() if posted else float("-inf")), merged.listing.id)


def _row(merged: MergedListing, key: str, report: GapReport | None) -> RankedListing:
    listing = merged.listing
    if report is None:
        return RankedListing(listing, merged.urls, ScoreStatus.UNSCORED, None, 0, 0, 0, False, None)
    result = report.score
    counts: dict[Support, int] = defaultdict(int, result.counts if result else {})
    has_score = result is not None and result.score is not None
    return RankedListing(
        listing=listing,
        urls=merged.urls,
        status=ScoreStatus.SCORED if has_score else ScoreStatus.NO_SCORE,
        score=result.score if result else None,
        strong=counts[Support.STRONG],
        partial=counts[Support.PARTIAL],
        none=counts[Support.NONE],
        incomplete=report.status is ReportStatus.INCOMPLETE,
        run_id=key,
    )


def _extraction_failure(report: GapReport) -> str | None:
    """The failure label when extraction failed, else None."""
    for reason in report.incomplete_reasons:
        if reason.startswith(_EXTRACTION_FAILED):
            return reason[len(_EXTRACTION_FAILED) :]
    return None


def _load_report(conn: sqlite3.Connection, key: str, version: str) -> GapReport | None:
    row = conn.execute(
        "SELECT report_json FROM discovery_report WHERE run_id = ? AND pipeline_version = ?",
        (key, version),
    ).fetchone()
    return GapReport.model_validate_json(row[0]) if row else None


def _store(
    conn: sqlite3.Connection,
    key: str,
    version: str,
    content_hash: str,
    report: GapReport,
    now: datetime,
) -> None:
    conn.execute(
        "INSERT INTO discovery_report"
        " (run_id, pipeline_version, content_hash, status, report_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (run_id, pipeline_version) DO UPDATE SET status = excluded.status,"
        " report_json = excluded.report_json, created_at = excluded.created_at",
        (
            key,
            version,
            content_hash,
            report.status.value,
            report.model_dump_json(),
            now.isoformat(),
        ),
    )
