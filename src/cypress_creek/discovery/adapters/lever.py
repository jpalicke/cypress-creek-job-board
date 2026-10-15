# ABOUTME: The Lever board adapter mapping: turns a public postings feed into listings.
# ABOUTME: The feed is hostile input. It is validated, normalized and never echoed in errors.
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from cypress_creek.discovery.adapters.base import (
    BoardFetch,
    FeedSchemaError,
    Listing,
    ListingState,
    SkippedJob,
    SkipReason,
    check_skip_budget,
    listing_id,
)
from cypress_creek.discovery.tombstones import normalize_board
from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.html_text import HtmlTextError, html_to_text
from cypress_creek.ingest.normalize import normalize, text_hash

ATS = "lever"

_MAX_FIELD_CHARS = 1000
_MAX_URL_CHARS = 2048
_ShortText = Annotated[str, StringConstraints(max_length=_MAX_FIELD_CHARS)]
# A posting id becomes part of the listing id, so it must be short and plain. This is also the
# rule for keeping a posting id in a skip, so that no feed text rides along.
_PLAIN_POSTING_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PART_SEPARATOR = "\n\n"


class _FeedModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class _Categories(_FeedModel):
    location: _ShortText | None = None


class _ListEntry(_FeedModel):
    text: _ShortText
    content: str


class _Posting(_FeedModel):
    id: str
    text: _ShortText
    hostedUrl: Annotated[str, StringConstraints(max_length=_MAX_URL_CHARS)]  # noqa: N815
    createdAt: int | None = None  # noqa: N815
    categories: _Categories | None = None
    description: str | None = None
    lists: list[_ListEntry] | None = None
    additional: str | None = None

    @field_validator("id")
    @classmethod
    def _plain_id(cls, value: str) -> str:
        if not _PLAIN_POSTING_ID.fullmatch(value):
            raise ValueError("not a plain posting id")
        return value

    @field_validator("hostedUrl")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("not an http(s) url")
        return value

    @field_validator("createdAt")
    @classmethod
    def _representable_time(cls, value: int | None) -> int | None:
        if value is not None:
            _from_epoch_milliseconds(value)
        return value


_PostingList = TypeAdapter(list[Any])


def _from_epoch_milliseconds(milliseconds: int) -> datetime:
    """The UTC time for epoch milliseconds. Raises ValueError when it is not representable."""
    try:
        return _EPOCH + timedelta(milliseconds=milliseconds)
    except OverflowError:
        raise ValueError("time out of range") from None


def _field_path(location: tuple[int | str, ...]) -> str:
    """A path such as lists[0].text. An error on the whole value is named $."""
    path = ""
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else f"{'.' if path else ''}{part}"
    return path or "$"


def _plain_line(raw: str) -> str:
    """Hostile text as one plain line: control characters stripped, whitespace collapsed."""
    try:
        text, _ = normalize(raw)
    except EmptyPosting:
        return ""
    return " ".join(text.split())


def _skip(index: int, raw: object, field: str, reason: SkipReason) -> SkippedJob:
    return SkippedJob(index=index, job_id=_plain_posting_id(raw), field=field, reason_code=reason)


def _plain_posting_id(raw: object) -> str | None:
    """The posting's own id as text, only when it is a short plain string."""
    posting_id = raw.get("id") if isinstance(raw, dict) else None
    if isinstance(posting_id, str) and _PLAIN_POSTING_ID.fullmatch(posting_id):
        return posting_id
    return None


def _validated_posting(raw: object) -> _Posting | str:
    """The posting model for one raw posting, or the field path of its first problem."""
    try:
        return _Posting.model_validate(raw)
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        return _field_path(error.errors()[0]["loc"])


def _description_text(posting: _Posting) -> str:
    """The description, each list heading with its content, then the additional text.

    The parts are converted to text one at a time and joined by blank lines, so that the end of
    one part never runs into the start of the next.
    """
    parts: list[str] = []
    if posting.description:
        parts.append(html_to_text(posting.description.encode("utf-8")).text)
    for entry in posting.lists or []:
        parts.append(_plain_line(entry.text))
        parts.append(html_to_text(entry.content.encode("utf-8")).text)
    if posting.additional:
        parts.append(html_to_text(posting.additional.encode("utf-8")).text)
    return _PART_SEPARATOR.join(part for part in parts if part)


def _map_posting(slug: str, index: int, raw: object, fetched_at: datetime) -> Listing | SkippedJob:
    posting = _validated_posting(raw)
    if isinstance(posting, str):
        return _skip(index, raw, posting, SkipReason.INVALID_FIELD)
    title = _plain_line(posting.text)
    if not title:
        return _skip(index, raw, "text", SkipReason.EMPTY_TEXT)
    try:
        content_text, _ = normalize(_description_text(posting))
    except EmptyPosting:
        return _skip(index, raw, "description", SkipReason.EMPTY_TEXT)
    except PostingTooLong:
        return _skip(index, raw, "description", SkipReason.CONTENT_TOO_LONG)
    except HtmlTextError:
        return _skip(index, raw, "description", SkipReason.CONTENT_UNREADABLE)
    location = posting.categories.location if posting.categories else None
    return Listing(
        id=listing_id(ATS, slug, posting.id),
        ats=ATS,
        slug=normalize_board(ATS, slug)[1],
        title=title,
        location=_plain_line(location or ""),
        url=posting.hostedUrl,
        posted_at=(
            None if posting.createdAt is None else _from_epoch_milliseconds(posting.createdAt)
        ),
        fetched_at=fetched_at,
        content_text=content_text,
        content_hash=text_hash(content_text),
        state=ListingState.NEW,
    )


def parse_postings_response(slug: str, body: bytes, fetched_at: datetime) -> BoardFetch:
    """Map a postings response to listings, skipping each malformed posting.

    The body is a JSON array of postings. A body of any other shape raises FeedSchemaError for the
    whole board. So does a board that loses more postings than the skip budget allows.
    """
    try:
        postings = _PostingList.validate_json(body)
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        raise FeedSchemaError(_field_path(error.errors()[0]["loc"])) from None
    listings: list[Listing] = []
    skipped: list[SkippedJob] = []
    for index, raw in enumerate(postings):
        mapped = _map_posting(slug, index, raw, fetched_at)
        if isinstance(mapped, SkippedJob):
            skipped.append(mapped)
        else:
            listings.append(mapped)
    check_skip_budget(len(postings), len(skipped))
    return BoardFetch(listings=tuple(listings), skipped=tuple(skipped))
