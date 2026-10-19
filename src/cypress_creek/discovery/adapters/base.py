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


class SkipReason(StrEnum):
    """Why one job was left out of a board. Stable strings, never a feed value."""

    INVALID_FIELD = "invalid_field"
    EMPTY_TEXT = "empty_text"
    CONTENT_TOO_LONG = "content_too_long"
    CONTENT_UNREADABLE = "content_unreadable"


@dataclass(frozen=True)
class SkippedJob:
    """One job left out of a board because it was malformed, with where and why.

    index is the position in the feed's jobs array. job_id is only set when the feed's own id is
    short and plain. field is the path inside the job, such as title. No feed value is stored.
    """

    index: int
    job_id: str | None
    field: str
    reason_code: SkipReason

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("a skipped job needs a non negative index")
        if not self.field:
            raise ValueError("a skipped job needs a field")


@dataclass(frozen=True)
class BoardFetch:
    """What one board fetch produced: the mapped listings and the jobs skipped.

    unlisted is the count of jobs the feed marks as not listed. They are dropped on purpose, so
    they are neither listings nor skipped jobs, and they do not count toward the skip budget.
    """

    listings: tuple[Listing, ...]
    skipped: tuple[SkippedJob, ...]
    unlisted: int = 0


# A board whose skipped jobs exceed this fraction of its jobs fails entirely with
# FeedSchemaError. A feed wide change must not shrink the board silently, because the missing
# jobs would later look closed.
MAX_SKIPPED_FRACTION = 0.1


def check_skip_budget(total: int, skipped: int) -> None:
    """Raise FeedSchemaError for the jobs field when skipped / total exceeds the budget.

    An empty board is valid. The error names only the field, never a count or a feed value.
    """
    if total < 0 or skipped < 0 or skipped > total:
        raise ValueError("job counts must satisfy 0 <= skipped <= total")
    if skipped and skipped / total > MAX_SKIPPED_FRACTION:
        raise FeedSchemaError("jobs")


class BoardAdapter(Protocol):
    """What every ATS adapter offers: read a whole board, or check that a board exists."""

    def fetch_board(self, slug: str) -> BoardFetch: ...

    def probe(self, slug: str) -> ExistenceResult: ...
