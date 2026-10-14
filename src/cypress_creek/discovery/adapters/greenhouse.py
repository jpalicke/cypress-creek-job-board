# ABOUTME: The Greenhouse board adapter: fetches a public board feed and maps it to listings.
# ABOUTME: The feed is hostile input. It is validated, normalized and never echoed in errors.
import html
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    field_validator,
)

from cypress_creek.discovery.adapters.base import (
    BoardNotFound,
    ExistenceResult,
    FeedSchemaError,
    Listing,
    ListingState,
    listing_id,
)
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


class _FeedModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class _Location(_FeedModel):
    name: _ShortText | None = None


class _Job(_FeedModel):
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


class _JobsResponse(_FeedModel):
    jobs: list[_Job]


class _BoardInfo(_FeedModel):
    name: _ShortText


def _field_path(location: tuple[int | str, ...]) -> str:
    """A path such as jobs[3].title. An error on the whole body is named $."""
    path = ""
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else f"{'.' if path else ''}{part}"
    return path or "$"


def _validated[ModelT: _FeedModel](model: type[ModelT], body: bytes) -> ModelT:
    try:
        return model.model_validate_json(body)
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        raise FeedSchemaError(_field_path(error.errors()[0]["loc"])) from None


def _plain_line(raw: str) -> str:
    """Hostile text as one plain line: control characters stripped, whitespace collapsed."""
    try:
        text, _ = normalize(raw)
    except EmptyPosting:
        return ""
    return " ".join(text.split())


def _job_to_listing(slug: str, index: int, job: _Job, fetched_at: datetime) -> Listing:
    title = _plain_line(job.title)
    if not title:
        raise FeedSchemaError(f"jobs[{index}].title")
    try:
        description = html_to_text(html.unescape(job.content).encode("utf-8")).text
        content_text, _ = normalize(description)
    except (EmptyPosting, PostingTooLong, HtmlTextError):
        raise FeedSchemaError(f"jobs[{index}].content") from None
    return Listing(
        id=listing_id(ATS, slug, str(job.id)),
        ats=ATS,
        slug=normalize_board(ATS, slug)[1],
        title=title,
        location=_plain_line(job.location.name or "") if job.location else "",
        url=job.absolute_url,
        posted_at=job.first_published,
        fetched_at=fetched_at,
        content_text=content_text,
        content_hash=text_hash(content_text),
        state=ListingState.NEW,
    )


def parse_jobs_response(slug: str, body: bytes, fetched_at: datetime) -> list[Listing]:
    """Map a board jobs response to listings. Raises FeedSchemaError naming the bad field."""
    response = _validated(_JobsResponse, body)
    return [
        _job_to_listing(slug, index, job, fetched_at) for index, job in enumerate(response.jobs)
    ]


def parse_board_name(body: bytes) -> str:
    """The organization name from a board info response, as one plain line."""
    name = _plain_line(_validated(_BoardInfo, body).name)
    if not name:
        raise FeedSchemaError("name")
    return name


class GreenhouseAdapter:
    """Reads public Greenhouse boards. Every request is a GET through the polite client."""

    def __init__(self, client: PoliteClient, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    def fetch_board(self, slug: str) -> list[Listing]:
        """Every job on the board. Raises BoardNotFound when Greenhouse has no such board."""
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
