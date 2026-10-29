# ABOUTME: GET and POST /api/watchlist: the approved companies, and adding one by human approval.
# ABOUTME: A name proposed by a model is never accepted here, and a blacklisted company is refused.
from contextlib import closing
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.responses import JSONResponse

from cypress_creek.api.context import DatabasePath
from cypress_creek.api.errors import ApiError, ErrorCode, ErrorDetail
from cypress_creek.discovery.blacklist import Candidate, is_blacklisted
from cypress_creek.discovery.blacklist_repository import Blacklist
from cypress_creek.discovery.tombstones import InvalidBoard
from cypress_creek.discovery.watchlist import (
    AlreadyWatched,
    IdentityEvidence,
    Tombstoned,
    Watchlist,
    WatchlistEntry,
)
from cypress_creek.storage.company_key import CompanyNameError
from cypress_creek.storage.db import connect

router = APIRouter()

MAX_NAME_CHARS = 200
MAX_ATS_CHARS = 50
MAX_SLUG_CHARS = 200
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WatchlistRequest(BaseModel):
    """What a person confirmed. The approval marker is required, and nothing else is accepted.

    There is no field for who proposed the name, so a model's suggestion cannot arrive here as
    if a person had approved it. The approval time is stamped by the server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: Annotated[Text, StringConstraints(max_length=MAX_NAME_CHARS)]
    ats: Annotated[Text, StringConstraints(max_length=MAX_ATS_CHARS)]
    slug: Annotated[Text, StringConstraints(max_length=MAX_SLUG_CHARS)]
    identity_evidence: IdentityEvidence
    approval: Literal["human_confirmed"]


class WatchlistEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_key: str
    display_name: str
    ats: str
    slug: str
    identity_evidence: IdentityEvidence
    approved_at: datetime
    region: str | None


class WatchlistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: list[WatchlistEntryResponse]


def _view(entry: WatchlistEntry) -> WatchlistEntryResponse:
    return WatchlistEntryResponse(
        company_key=entry.company_key,
        display_name=entry.display_name,
        ats=entry.ats,
        slug=entry.slug,
        identity_evidence=entry.identity_evidence,
        approved_at=entry.approved_at,
        region=entry.region.value if entry.region else None,
    )


@router.get("/api/watchlist")
def list_watchlist(database: DatabasePath) -> WatchlistResponse:
    with closing(connect(database)) as conn:
        entries = Watchlist(conn).entries()
    return WatchlistResponse(entries=[_view(entry) for entry in entries])


@router.post("/api/watchlist", status_code=201)
def add_to_watchlist(request: WatchlistRequest, database: DatabasePath) -> JSONResponse:
    try:
        entry = WatchlistEntry(
            display_name=request.display_name,
            ats=request.ats,
            slug=request.slug,
            identity_evidence=request.identity_evidence,
            approved_at=datetime.now(UTC),
        )
    except CompanyNameError:
        raise ApiError(
            422,
            ErrorCode.INVALID_REQUEST,
            [ErrorDetail(field="display_name", problem="not a usable company name")],
        ) from None
    except InvalidBoard:
        raise ApiError(
            422,
            ErrorCode.INVALID_REQUEST,
            [ErrorDetail(field="slug", problem="not a usable board")],
        ) from None
    with closing(connect(database)) as conn:
        blocked = is_blacklisted(
            Candidate(entry.display_name, entry.slug, None), Blacklist(conn).entries()
        )
        if blocked is not None:
            raise ApiError(409, ErrorCode.BLACKLISTED)
        try:
            Watchlist(conn).add(entry)
        except Tombstoned:
            raise ApiError(409, ErrorCode.TOMBSTONED) from None
        except AlreadyWatched:
            raise ApiError(409, ErrorCode.ALREADY_WATCHED) from None
    return JSONResponse(_view(entry).model_dump(mode="json"), status_code=201)
