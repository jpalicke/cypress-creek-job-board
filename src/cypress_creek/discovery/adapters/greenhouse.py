# ABOUTME: The Greenhouse board adapter: fetches a public board feed and maps it to listings.
# ABOUTME: The feed is hostile input. It is validated, normalized and never echoed in errors.
import html
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from pydantic import StringConstraints, ValidationError, field_validator

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

ATS = "greenhouse"
DEFAULT_BASE_URL = "https://boards-api.greenhouse.io"
# A board of several hundred jobs with full descriptions is many megabytes of JSON.
GREENHOUSE_FETCH_LIMITS = FetchLimits(
    max_wire_bytes=64 * 1024 * 1024,
    max_decoded_bytes=64 * 1024 * 1024,
    total_timeout=60.0,
    content_types=frozenset({"application/json"}),
)

_MAX_FIELD_CHARS = 1000
_MAX_URL_CHARS = 2048
_ShortText = Annotated[str, StringConstraints(max_length=_MAX_FIELD_CHARS)]
# A job id is kept in a skip only when it is short and plain, so that no feed text rides along.
_PLAIN_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class _Location(FeedModel):
    name: _ShortText | None = None


class _Job(FeedModel):
    id: int
    title: _ShortText
    location: _Location | None = None
    absolute_url: Annotated[str, StringConstraints(max_length=_MAX_URL_CHARS)]
    first_published: datetime | None = None
    content: str

    @field_validator("absolute_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("not an http(s) url")
        return value


class _JobsResponse(FeedModel):
    """The top level of a jobs response. Each job is validated on its own, later."""

    jobs: list[Any]


class _BoardInfo(FeedModel):
    name: _ShortText


def _validated[ModelT: FeedModel](model: type[ModelT], body: bytes) -> ModelT:
    try:
        return model.model_validate_json(body)
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        raise FeedSchemaError(field_path(error.errors()[0]["loc"])) from None


def _skip(index: int, raw: object, field: str, reason: SkipReason) -> SkippedJob:
    return SkippedJob(index=index, job_id=_plain_job_id(raw), field=field, reason_code=reason)


def _plain_job_id(raw: object) -> str | None:
    """The job's own id as text, only when it is a plain int or a short plain string."""
    job_id = raw.get("id") if isinstance(raw, dict) else None
    if isinstance(job_id, bool) or not isinstance(job_id, int | str):
        return None
    text = str(job_id)
    return text if _PLAIN_JOB_ID.fullmatch(text) else None


def _validated_job(raw: object) -> _Job | str:
    """The job model for one raw job, or the field path of its first problem."""
    try:
        # Validated as JSON text so that strict typing still accepts a date string.
        return _Job.model_validate_json(json.dumps(raw))
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        return field_path(error.errors()[0]["loc"])


def _map_job(slug: str, index: int, raw: object, fetched_at: datetime) -> Listing | SkippedJob:
    job = _validated_job(raw)
    if isinstance(job, str):
        return _skip(index, raw, job, SkipReason.INVALID_FIELD)
    title = plain_line(job.title)
    if not title:
        return _skip(index, raw, "title", SkipReason.EMPTY_TEXT)
    try:
        description = html_to_text(html.unescape(job.content).encode("utf-8")).text
        content_text, _ = normalize(description)
    except EmptyPosting:
        return _skip(index, raw, "content", SkipReason.EMPTY_TEXT)
    except PostingTooLong:
        return _skip(index, raw, "content", SkipReason.CONTENT_TOO_LONG)
    except HtmlTextError:
        return _skip(index, raw, "content", SkipReason.CONTENT_UNREADABLE)
    return Listing(
        id=listing_id(ATS, slug, str(job.id)),
        ats=ATS,
        slug=normalize_board(ATS, slug)[1],
        title=title,
        location=plain_line(job.location.name or "") if job.location else "",
        url=job.absolute_url,
        posted_at=job.first_published,
        fetched_at=fetched_at,
        content_text=content_text,
        content_hash=text_hash(content_text),
        state=ListingState.NEW,
    )


def parse_jobs_response(slug: str, body: bytes, fetched_at: datetime) -> BoardFetch:
    """Map a board jobs response to listings, skipping each malformed job.

    A body or jobs list of the wrong shape raises FeedSchemaError for the whole board. So does a
    board that loses more jobs than the skip budget allows.
    """
    response = _validated(_JobsResponse, body)
    listings: list[Listing] = []
    skipped: list[SkippedJob] = []
    for index, raw in enumerate(response.jobs):
        mapped = _map_job(slug, index, raw, fetched_at)
        if isinstance(mapped, SkippedJob):
            skipped.append(mapped)
        else:
            listings.append(mapped)
    check_skip_budget(len(response.jobs), len(skipped))
    return BoardFetch(listings=tuple(listings), skipped=tuple(skipped))


def parse_board_name(body: bytes) -> str:
    """The organization name from a board info response, as one plain line."""
    name = plain_line(_validated(_BoardInfo, body).name)
    if not name:
        raise FeedSchemaError("name")
    return name


class GreenhouseAdapter:
    """Reads public Greenhouse boards. Every request is a GET through the polite client."""

    def __init__(self, client: PoliteClient, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    def fetch_board(self, slug: str) -> BoardFetch:
        """Every job on the board, and the jobs skipped. Raises BoardNotFound when it is missing."""
        board = self._board_url(slug)
        response = self._get(f"{board}/jobs?content=true", slug)
        fetched_at = datetime.fromtimestamp(response.fetched_at, UTC)
        return parse_jobs_response(slug, response.body, fetched_at)

    def probe(self, slug: str) -> ExistenceResult:
        """Whether the board exists, with the organization name it reports."""
        try:
            response = self._get(self._board_url(slug), slug)
        except BoardNotFound:
            return ExistenceResult(found=False, organization_name=None)
        return ExistenceResult(found=True, organization_name=parse_board_name(response.body))

    def _board_url(self, slug: str) -> str:
        _, board = normalize_board(ATS, slug)
        return f"{self._base_url}/v1/boards/{quote(board, safe='')}"

    def _get(self, url: str, slug: str) -> CachedResponse:
        try:
            return self._client.get(url)
        except NotFound:
            # Only a 404 means the board does not exist. Any other refused status, such as a
            # 403 or a 410, propagates as a transport error and is never reported as missing.
            raise BoardNotFound(ATS, slug) from None
