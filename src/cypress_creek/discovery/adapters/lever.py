# ABOUTME: The Lever board adapter mapping: turns a public postings feed into listings.
# ABOUTME: The feed is hostile input. It is validated, normalized and never echoed in errors.
import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from pydantic import StringConstraints, TypeAdapter, ValidationError, field_validator

from cypress_creek.discovery.adapters.base import (
    BoardFetch,
    BoardNotFound,
    ExistenceResult,
    FeedSchemaError,
    Listing,
    ListingState,
    SkippedJob,
    SkipReason,
    check_skip_budget,
    listing_id,
)
from cypress_creek.discovery.adapters.feed_common import FeedModel, field_path, plain_line
from cypress_creek.discovery.polite_client import CachedResponse, NotFound, PoliteClient
from cypress_creek.discovery.tombstones import normalize_board
from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.html_text import HtmlTextError, html_to_text
from cypress_creek.ingest.normalize import normalize, text_hash
from cypress_creek.ingest.safe_http import FetchLimits

ATS = "lever"

_MAX_FIELD_CHARS = 1000
_MAX_URL_CHARS = 2048
_ShortText = Annotated[str, StringConstraints(max_length=_MAX_FIELD_CHARS)]
# A posting id becomes part of the listing id, so it must be short and plain. This is also the
# rule for keeping a posting id in a skip, so that no feed text rides along.
_PLAIN_POSTING_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PART_SEPARATOR = "\n\n"


class _Categories(FeedModel):
    location: _ShortText | None = None


class _ListEntry(FeedModel):
    text: _ShortText
    content: str


class _Posting(FeedModel):
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
        return field_path(error.errors()[0]["loc"])


def _description_text(posting: _Posting) -> str:
    """The description, each list heading with its content, then the additional text.

    The parts are converted to text one at a time and joined by blank lines, so that the end of
    one part never runs into the start of the next.
    """
    parts: list[str] = []
    if posting.description:
        parts.append(html_to_text(posting.description.encode("utf-8")).text)
    for entry in posting.lists or []:
        parts.append(plain_line(entry.text))
        parts.append(html_to_text(entry.content.encode("utf-8")).text)
    if posting.additional:
        parts.append(html_to_text(posting.additional.encode("utf-8")).text)
    return _PART_SEPARATOR.join(part for part in parts if part)


def _map_posting(slug: str, index: int, raw: object, fetched_at: datetime) -> Listing | SkippedJob:
    posting = _validated_posting(raw)
    if isinstance(posting, str):
        return _skip(index, raw, posting, SkipReason.INVALID_FIELD)
    title = plain_line(posting.text)
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
        location=plain_line(location or ""),
        url=posting.hostedUrl,
        posted_at=(
            None if posting.createdAt is None else _from_epoch_milliseconds(posting.createdAt)
        ),
        fetched_at=fetched_at,
        content_text=content_text,
        content_hash=text_hash(content_text),
        state=ListingState.NEW,
    )


def load_postings(body: bytes) -> list[Any]:
    """The raw postings of one response page. A body that is not a JSON array is a schema error."""
    try:
        return _PostingList.validate_json(body)
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        raise FeedSchemaError(field_path(error.errors()[0]["loc"])) from None


def map_postings(slug: str, postings: list[Any], fetched_at: datetime) -> BoardFetch:
    """Map raw postings to listings, skipping each malformed posting.

    A skip's index is the position in postings. A board that loses more postings than the skip
    budget allows raises FeedSchemaError.
    """
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


def parse_postings_response(slug: str, body: bytes, fetched_at: datetime) -> BoardFetch:
    """Map a postings response to listings, skipping each malformed posting.

    The body is a JSON array of postings. A body of any other shape raises FeedSchemaError for the
    whole board. So does a board that loses more postings than the skip budget allows.
    """
    return map_postings(slug, load_postings(body), fetched_at)


class LeverRegion(StrEnum):
    US = "us"
    EU = "eu"


DEFAULT_US_BASE_URL = "https://api.lever.co/v0/postings"
DEFAULT_EU_BASE_URL = "https://api.eu.lever.co/v0/postings"
MAX_PAGE_SIZE = 100
# A board is read page by page. Fifty full pages is 5000 postings at the largest page size. A
# board still full at the cap fails, so that a board is never returned silently truncated.
MAX_PAGES = 50
# A real page of 100 postings with full descriptions measured 1.9 MB on 2026-10-14. The cap leaves
# about eight times that, for boards with long descriptions.
LEVER_FETCH_LIMITS = FetchLimits(
    max_wire_bytes=16 * 1024 * 1024,
    max_decoded_bytes=16 * 1024 * 1024,
    total_timeout=60.0,
    content_types=frozenset({"application/json"}),
)


def _without_repeats(postings: list[Any], seen: set[str]) -> list[Any]:
    """The postings whose own id is not in seen yet, adding their ids to seen.

    The list can shift between page requests, so one posting may arrive twice. The first copy
    stays. A posting without a plain id cannot repeat, and is left for the mapper to skip.
    """
    kept: list[Any] = []
    for raw in postings:
        posting_id = _plain_posting_id(raw)
        if posting_id is not None:
            if posting_id in seen:
                continue
            seen.add(posting_id)
        kept.append(raw)
    return kept


class LeverAdapter:
    """Reads public Lever boards. Every request is a GET through the polite client.

    Lever serves a board from a US host or an EU host. Which one is found by asking the US host
    first, and the answer is remembered in memory for later fetches of that board. A caller may
    seed it with `remember_region` from a region it stored.
    """

    def __init__(
        self,
        client: PoliteClient,
        *,
        us_base_url: str = DEFAULT_US_BASE_URL,
        eu_base_url: str = DEFAULT_EU_BASE_URL,
        page_size: int = MAX_PAGE_SIZE,
    ) -> None:
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        self._client = client
        self._base_urls = {
            LeverRegion.US: us_base_url.rstrip("/"),
            LeverRegion.EU: eu_base_url.rstrip("/"),
        }
        self._page_size = page_size
        self._regions: dict[str, LeverRegion] = {}

    def region_of(self, slug: str) -> LeverRegion | None:
        """The region a board was last found in, or None when it is not known."""
        return self._regions.get(normalize_board(ATS, slug)[1])

    def remember_region(self, slug: str, region: LeverRegion) -> None:
        """Seed the region of a board from an earlier run, so the first fetch asks one host."""
        self._regions[normalize_board(ATS, slug)[1]] = region

    def probe(self, slug: str) -> ExistenceResult:
        """Whether the board exists on either host. Lever reports no organization name."""
        board = normalize_board(ATS, slug)[1]
        found = self._first_page(board, tuple(LeverRegion), limit=1)
        if found is None:
            self._regions.pop(board, None)
            return ExistenceResult(found=False, organization_name=None)
        self._regions[board] = found[0]
        return ExistenceResult(found=True, organization_name=None)

    def fetch_board(self, slug: str) -> BoardFetch:
        """Every posting on the board, and the postings skipped.

        Raises BoardNotFound when no host has the board, and FeedSchemaError when the board is
        still full after MAX_PAGES pages.
        """
        board = normalize_board(ATS, slug)[1]
        known = self._regions.get(board)
        found = self._first_page(board, (known,) if known else tuple(LeverRegion), self._page_size)
        if found is None:
            self._regions.pop(board, None)
            raise BoardNotFound(ATS, slug)
        region, response = found
        fetched_at = datetime.fromtimestamp(response.fetched_at, UTC)
        postings: list[Any] = []
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            if page:
                later = self._get_page(region, board, self._page_size, page * self._page_size)
                if later is None:
                    self._regions.pop(board, None)
                    raise BoardNotFound(ATS, slug)
                response = later
            page_postings = load_postings(response.body)
            postings.extend(_without_repeats(page_postings, seen))
            if len(page_postings) < self._page_size:
                self._regions[board] = region
                return map_postings(slug, postings, fetched_at)
        raise FeedSchemaError("jobs")

    def _first_page(
        self, board: str, regions: tuple[LeverRegion, ...], limit: int
    ) -> tuple[LeverRegion, CachedResponse] | None:
        """The first region, in order, that has the board, with its first page."""
        for region in regions:
            response = self._get_page(region, board, limit, 0)
            if response is not None:
                return region, response
        return None

    def _get_page(
        self, region: LeverRegion, board: str, limit: int, skip: int
    ) -> CachedResponse | None:
        url = f"{self._base_urls[region]}/{quote(board, safe='')}"
        try:
            return self._client.get(f"{url}?mode=json&limit={limit}&skip={skip}")
        except NotFound:
            # Only a 404 means the host has no such board. Any other refused status, such as a
            # 403 or a 410, propagates as a transport error and is never reported as missing.
            return None
