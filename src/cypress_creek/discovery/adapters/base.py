# ABOUTME: The adapter contract: the Listing row, ExistenceResult, the BoardAdapter protocol.
# ABOUTME: Also the typed adapter errors, none of which echo values taken from a feed.
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from cypress_creek.discovery.tombstones import normalize_board


class ListingState(StrEnum):
    NEW = "new"
    SEEN = "seen"
    CLOSED = "closed"


def listing_id(ats: str, slug: str, job_id: str) -> str:
    """The one listing id format, ats:slug:job_id. Raises ValueError on an empty job id."""
    ats_part, slug_part = normalize_board(ats, slug)
    job_part = job_id.strip()
    if not job_part:
        raise ValueError("a listing needs a job id")
    return f"{ats_part}:{slug_part}:{job_part}"


@dataclass(frozen=True)
class Listing:
    """One job posting on a watched board, shaped like a row of the listing table."""

    id: str
    ats: str
    slug: str
    title: str
    location: str
    url: str
    posted_at: datetime | None
    fetched_at: datetime
    content_text: str
    content_hash: str
    state: ListingState = ListingState.NEW


class AdapterError(Exception):
    """Base of every adapter failure. The reason code is a stable, value free string."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class FeedSchemaError(AdapterError):
    """A feed did not have the expected shape. Names the field path, never a feed value."""

    def __init__(self, field: str) -> None:
        super().__init__("feed_schema")
        self.field = field

    def __str__(self) -> str:
        return f"feed_schema at {self.field}"


class BoardNotFound(AdapterError):
    """The ATS has no board for this slug."""

    def __init__(self, ats: str, slug: str) -> None:
        super().__init__("board_not_found")
        self.ats = ats
        self.slug = slug

    def __str__(self) -> str:
        return f"board_not_found: {self.ats}/{self.slug}"


@dataclass(frozen=True)
class ExistenceResult:
    """Whether a board exists, and the organization name the ATS reports for it, if any."""

    found: bool
    organization_name: str | None

    def __post_init__(self) -> None:
        if not self.found and self.organization_name is not None:
            raise ValueError("a board that was not found cannot have an organization name")


class BoardAdapter(Protocol):
    """What every ATS adapter offers: read a whole board, or check that a board exists."""

    def fetch_board(self, slug: str) -> list[Listing]: ...

    def probe(self, slug: str) -> ExistenceResult: ...
