# ABOUTME: The Ashby board adapter mapping: turns a public job board feed into listings.
# ABOUTME: The feed is hostile input. It is validated, normalized and never echoed in errors.
import json
import re
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import AwareDatetime, StringConstraints, ValidationError, field_validator

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
from cypress_creek.discovery.adapters.feed_common import FeedModel, field_path, plain_line
from cypress_creek.discovery.tombstones import normalize_board
from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.html_text import HtmlTextError, html_to_text
from cypress_creek.ingest.normalize import normalize, text_hash

ATS = "ashby"

_MAX_FIELD_CHARS = 1000
_MAX_URL_CHARS = 2048
_ShortText = Annotated[str, StringConstraints(max_length=_MAX_FIELD_CHARS)]
# A job id becomes part of the listing id, so it must be short and plain. This is also the rule
# for keeping a job id in a skip, so that no feed text rides along.
_PLAIN_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class _Job(FeedModel):
    id: str
    title: _ShortText
    location: _ShortText | None = None
    publishedAt: AwareDatetime | None = None  # noqa: N815
    # Required: a job that does not say whether it is listed is malformed, never assumed listed.
    isListed: bool  # noqa: N815
    jobUrl: Annotated[str, StringConstraints(max_length=_MAX_URL_CHARS)]  # noqa: N815
    descriptionPlain: str | None = None  # noqa: N815
    descriptionHtml: str | None = None  # noqa: N815

    @field_validator("id")
    @classmethod
    def _plain_id(cls, value: str) -> str:
        if not _PLAIN_JOB_ID.fullmatch(value):
            raise ValueError("not a plain job id")
        return value

    @field_validator("jobUrl")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("not an http(s) url")
        return value


class _BoardResponse(FeedModel):
    """The top level of a board response. Each job is validated on its own, later."""

    jobs: list[Any]


def _skip(index: int, raw: object, field: str, reason: SkipReason) -> SkippedJob:
    return SkippedJob(index=index, job_id=_plain_job_id(raw), field=field, reason_code=reason)


def _plain_job_id(raw: object) -> str | None:
    """The job's own id as text, only when it is a short plain string."""
    job_id = raw.get("id") if isinstance(raw, dict) else None
    if isinstance(job_id, str) and _PLAIN_JOB_ID.fullmatch(job_id):
        return job_id
    return None


def _is_unlisted(raw: object) -> bool:
    """Whether the job says it is not listed, judged from isListed alone.

    Only the JSON false counts. The check comes before any other validation, so that a job the
    feed marks as unlisted is dropped and cannot cause skips with its other fields. Look alike
    values such as 0 or "false" are left to validation, which rejects them.
    """
    return isinstance(raw, dict) and raw.get("isListed") is False


def _validated_job(raw: object) -> _Job | str:
    """The job model for one raw job, or the field path of its first problem."""
    try:
        # Validated as JSON text so that strict typing still accepts a date string.
        return _Job.model_validate_json(json.dumps(raw))
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        return field_path(error.errors()[0]["loc"])


def _description_text(job: _Job) -> str:
    """The plain description when it has any text, else the html description as text.

    Raises EmptyPosting when neither has text. A plain description that is too long fails the
    job, since the html form would be at least as long.
    """
    if job.descriptionPlain:
        try:
            return normalize(job.descriptionPlain)[0]
        except EmptyPosting:
            pass
    if job.descriptionHtml:
        return normalize(html_to_text(job.descriptionHtml.encode("utf-8")).text)[0]
    raise EmptyPosting


def _map_job(slug: str, index: int, raw: object, fetched_at: datetime) -> Listing | SkippedJob:
    job = _validated_job(raw)
    if isinstance(job, str):
        return _skip(index, raw, job, SkipReason.INVALID_FIELD)
    title = plain_line(job.title)
    if not title:
        return _skip(index, raw, "title", SkipReason.EMPTY_TEXT)
    try:
        content_text = _description_text(job)
    except EmptyPosting:
        return _skip(index, raw, "description", SkipReason.EMPTY_TEXT)
    except PostingTooLong:
        return _skip(index, raw, "description", SkipReason.CONTENT_TOO_LONG)
    except HtmlTextError:
        return _skip(index, raw, "description", SkipReason.CONTENT_UNREADABLE)
    return Listing(
        id=listing_id(ATS, slug, job.id),
        ats=ATS,
        slug=normalize_board(ATS, slug)[1],
        title=title,
        location=plain_line(job.location or ""),
        url=job.jobUrl,
        posted_at=job.publishedAt,
        fetched_at=fetched_at,
        content_text=content_text,
        content_hash=text_hash(content_text),
        state=ListingState.NEW,
    )


def parse_board_response(slug: str, body: bytes, fetched_at: datetime) -> BoardFetch:
    """Map a board response to listings, skipping each malformed job.

    A body or jobs list of the wrong shape raises FeedSchemaError for the whole board. Jobs the
    feed marks as not listed are dropped and counted, not skipped. The skip budget is counted
    over the listed jobs only, so a board that is mostly unlisted is not a schema failure.
    """
    try:
        response = _BoardResponse.model_validate_json(body)
    except ValidationError as error:
        # Only the location of the first problem is used, never its message or input value.
        raise FeedSchemaError(field_path(error.errors()[0]["loc"])) from None
    listings: list[Listing] = []
    skipped: list[SkippedJob] = []
    unlisted = 0
    for index, raw in enumerate(response.jobs):
        if _is_unlisted(raw):
            unlisted += 1
            continue
        mapped = _map_job(slug, index, raw, fetched_at)
        if isinstance(mapped, SkippedJob):
            skipped.append(mapped)
        else:
            listings.append(mapped)
    check_skip_budget(len(response.jobs) - unlisted, len(skipped))
    return BoardFetch(listings=tuple(listings), skipped=tuple(skipped), unlisted=unlisted)
