# ABOUTME: GET and POST /api/blacklist and DELETE /api/blacklist/{id}: the blocked entries.
# ABOUTME: Values are normalized by the same rules the filter uses, so a variant is the same entry.
from contextlib import closing
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.responses import JSONResponse

from cypress_creek.api.context import DatabasePath
from cypress_creek.api.errors import ApiError, ErrorCode, ErrorDetail
from cypress_creek.discovery.blacklist import BlacklistEntry, BlockReason, InvalidBlacklistValue
from cypress_creek.discovery.blacklist_repository import AlreadyBlacklisted, Blacklist
from cypress_creek.storage.db import connect

router = APIRouter()

MAX_VALUE_CHARS = 500
MAX_REASON_CHARS = 1000
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class BlacklistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    match_kind: BlockReason
    value: Annotated[Text, StringConstraints(max_length=MAX_VALUE_CHARS)]
    reason: Annotated[Text, StringConstraints(max_length=MAX_REASON_CHARS)]


class BlacklistEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int
    match_kind: BlockReason
    value: str
    reason: str
    added_at: datetime


class BlacklistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: list[BlacklistEntryResponse]


class RemovedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    removed: bool


def _view(entry_id: int, entry: BlacklistEntry) -> BlacklistEntryResponse:
    return BlacklistEntryResponse(
        id=entry_id,
        match_kind=entry.match_kind,
        value=entry.value,
        reason=entry.reason,
        added_at=entry.added_at,
    )


@router.get("/api/blacklist")
def list_blacklist(database: DatabasePath) -> BlacklistResponse:
    with closing(connect(database)) as conn:
        rows = Blacklist(conn).rows()
    return BlacklistResponse(entries=[_view(entry_id, entry) for entry_id, entry in rows])


@router.post("/api/blacklist", status_code=201)
def add_to_blacklist(request: BlacklistRequest, database: DatabasePath) -> JSONResponse:
    try:
        entry = BlacklistEntry(request.match_kind, request.value, request.reason, datetime.now(UTC))
    except InvalidBlacklistValue:
        raise ApiError(
            422,
            ErrorCode.INVALID_REQUEST,
            [ErrorDetail(field="value", problem="not a usable value for this kind")],
        ) from None
    with closing(connect(database)) as conn:
        try:
            entry_id = Blacklist(conn).add(entry)
        except AlreadyBlacklisted:
            raise ApiError(409, ErrorCode.ALREADY_BLACKLISTED) from None
    return JSONResponse(_view(entry_id, entry).model_dump(mode="json"), status_code=201)


@router.delete("/api/blacklist/{entry_id}")
def remove_from_blacklist(entry_id: int, database: DatabasePath) -> RemovedResponse:
    with closing(connect(database)) as conn:
        if not Blacklist(conn).remove(entry_id):
            raise ApiError(404, ErrorCode.NOT_FOUND)
    return RemovedResponse(removed=True)
