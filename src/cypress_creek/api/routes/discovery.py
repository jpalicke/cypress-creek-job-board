# ABOUTME: Discovery routes: refresh the watched boards and score under a cap, and list the ranking.
# ABOUTME: The score is triage only. Nothing here applies, sends or posts anything anywhere.
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError

from cypress_creek.api.backends import BackendChoiceError, check_backend_choice
from cypress_creek.api.context import BankPath, DatabasePath
from cypress_creek.api.errors import ApiError, ErrorCode, details_from_validation_error
from cypress_creek.api.routes.facts import load_bank_or_raise
from cypress_creek.api.routes.postings import BackendDep
from cypress_creek.api.schemas import (
    BoardErrorResponse,
    DiscoveryListingsResponse,
    DiscoveryRefreshRequest,
    DiscoverySummaryResponse,
    RankedListingResponse,
)
from cypress_creek.discovery.adapters.base import BoardAdapter
from cypress_creek.discovery.blacklist_repository import Blacklist
from cypress_creek.discovery.factory import default_adapters, seed_lever_regions
from cypress_creek.discovery.filters import ListingFilters
from cypress_creek.discovery.run import (
    DEFAULT_CAP,
    RankedListing,
    RunIdentity,
    board_keys,
    ranked_listings,
    run_discovery,
    unblocked_entries,
)
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.ingest.models import Posting
from cypress_creek.pipeline.report import GapReport, ReportRefused
from cypress_creek.pipeline.run import analyze
from cypress_creek.providers import BudgetedProvider, BudgetTracker
from cypress_creek.providers.budget import budget_from_settings
from cypress_creek.storage.db import connect

router = APIRouter()

TRIAGE_NOTE = (
    "The score is for triage only. It is not a probability of being hired, and each score "
    "comes from a gap report you can open with its run id."
)


def adapters_of(request: Request) -> dict[str, BoardAdapter]:
    """The adapters the app was given, or the real ones, built on first use."""
    given: dict[str, BoardAdapter] | None = request.app.state.adapters
    if given is None:
        given = default_adapters()
        request.app.state.adapters = given
    return given


def summary_response(
    fetched: int,
    blocked: int,
    removed: dict[str, int],
    scored: int,
    hits: int,
    unscored: int,
    stopped_by: str | None,
    errors: list[BoardErrorResponse],
) -> DiscoverySummaryResponse:
    return DiscoverySummaryResponse.model_validate(
        {
            "fetched": fetched,
            "blocked_boards": blocked,
            "filtered_out": removed,
            "scored": scored,
            "cache_hits": hits,
            "unscored": unscored,
            "stopped_by": stopped_by,
            "errors": errors,
        }
    )


@router.post("/api/discovery/refresh")
def refresh_discovery(
    body: DiscoveryRefreshRequest,
    request: Request,
    backend: BackendDep,
    database: DatabasePath,
    bank_path: BankPath,
) -> DiscoverySummaryResponse:
    """Fetch every watched board that is not blacklisted, filter, score under the cap, rank."""
    try:
        check_backend_choice(
            body.backend,
            body.confirm_hosted,
            configured=backend.settings.provider,
            capabilities=backend.provider.capabilities,
        )
    except BackendChoiceError as error:
        raise ApiError(422, ErrorCode(error.code)) from None
    bank = load_bank_or_raise(bank_path)
    tracker = BudgetTracker(
        budget_from_settings(backend.settings), backend.provider.capabilities.cost_per_mtok
    )
    budgeted = BudgetedProvider(backend.provider, tracker)

    def analyzer(posting: Posting) -> GapReport:
        return analyze(
            posting,
            bank,
            budgeted,
            backend=backend.settings.provider,
            model=backend.settings.model,
        )

    identity = RunIdentity(
        bank_digest=bank_hash(bank), backend=backend.settings.provider, model=backend.settings.model
    )
    adapters = adapters_of(request)
    now = datetime.now(UTC)
    conn = connect(database)
    try:
        entries, _ = unblocked_entries(conn, Blacklist(conn).entries())
        seed_lever_regions(adapters, entries)
        try:
            result = run_discovery(
                conn,
                adapters,
                Blacklist(conn).entries(),
                body.filters,
                analyzer,
                identity,
                cap=DEFAULT_CAP if body.cap is None else body.cap,
                today=now.date(),
                now=now,
            )
        except ReportRefused:
            raise ApiError(422, ErrorCode.REPORT_REFUSED) from None
    finally:
        conn.close()
    summary = result.summary
    return summary_response(
        summary.fetched,
        summary.blocked_boards,
        {name.value: count for name, count in summary.filtered_out.items()},
        summary.scored,
        summary.cache_hits,
        summary.unscored,
        summary.stopped_by,
        [BoardErrorResponse(ats=e.ats, slug=e.slug, reason=e.reason) for e in summary.errors],
    )


def listing_response(row: RankedListing, today: date) -> RankedListingResponse:
    listing = row.listing
    posted = listing.posted_at
    return RankedListingResponse(
        id=listing.id,
        title=listing.title,
        location=listing.location,
        ats=listing.ats,
        slug=listing.slug,
        urls=list(row.urls),
        posted_at=posted,
        age_days=(today - posted.date()).days if posted else None,
        status=row.status.value,
        score=row.score,
        strong=row.strong,
        partial=row.partial,
        none=row.none,
        incomplete=row.incomplete,
        run_id=row.run_id,
    )


@router.get("/api/discovery/listings")
def discovery_listings(
    backend: BackendDep,
    database: DatabasePath,
    bank_path: BankPath,
    include_keyword: Annotated[list[str] | None, Query(max_length=50)] = None,
    exclude_keyword: Annotated[list[str] | None, Query(max_length=50)] = None,
    location: Annotated[list[str] | None, Query(max_length=50)] = None,
    exclude_seniority: Annotated[list[str] | None, Query(max_length=50)] = None,
    remote: bool | None = None,
    max_age_days: int | None = None,
) -> DiscoveryListingsResponse:
    """The ranked list of open listings on the watched boards, read back from storage."""
    try:
        filters = ListingFilters(
            include_keywords=tuple(include_keyword or ()),
            exclude_keywords=tuple(exclude_keyword or ()),
            locations=tuple(location or ()),
            remote=remote,
            exclude_seniority=tuple(exclude_seniority or ()),
            max_age_days=max_age_days,
        )
    except ValidationError as error:
        raise ApiError(
            422, ErrorCode.INVALID_REQUEST, details_from_validation_error(error)
        ) from None
    bank = load_bank_or_raise(bank_path)
    identity = RunIdentity(
        bank_digest=bank_hash(bank), backend=backend.settings.provider, model=backend.settings.model
    )
    now = datetime.now(UTC)
    conn = connect(database)
    try:
        entries, _ = unblocked_entries(conn, Blacklist(conn).entries())
        rows = ranked_listings(conn, board_keys(entries), filters, identity, now.date())
    finally:
        conn.close()
    return DiscoveryListingsResponse(
        note=TRIAGE_NOTE, listings=[listing_response(row, now.date()) for row in rows]
    )
