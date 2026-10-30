# ABOUTME: Request and response models for the posting, analyze, report and fact routes.
# ABOUTME: Every body is a pydantic model that forbids extra fields, so unknown input is refused.
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cypress_creek.discovery.filters import ListingFilters
from cypress_creek.facts.models import Fact
from cypress_creek.ingest.models import PostingSource, PostingWarning
from cypress_creek.pipeline.report import GapReport
from cypress_creek.storage.repository import StoredVerdict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PostingRequest(ApiModel):
    """A pasted text or a link. Exactly one of `text` and `url` goes with its `source`."""

    source: Literal["paste", "link"]
    text: str | None = None
    url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def _one_input(self) -> "PostingRequest":
        if self.source == "paste" and (self.text is None or self.url is not None):
            raise ValueError("a paste needs text and no url")
        if self.source == "link" and (self.url is None or self.text is not None):
            raise ValueError("a link needs a url and no text")
        return self


class ExtractionWarning(ApiModel):
    kind: str
    count: int


class PostingResponse(ApiModel):
    id: str
    source: PostingSource
    text: str
    text_hash: str
    origin_url: str | None
    warnings: list[PostingWarning]
    extraction_warnings: list[ExtractionWarning]
    fetch_warnings: list[str]
    created_at: datetime


class AnalyzeRequest(ApiModel):
    backend: str = Field(min_length=1, max_length=100)
    confirm_hosted: bool = False


class AnalyzeResponse(ApiModel):
    report_id: str
    report: GapReport


class ReportResponse(ApiModel):
    report_id: str
    posting_id: str
    created_at: datetime
    report: GapReport
    validator_verdicts: list[StoredVerdict]


class EstimateResponse(ApiModel):
    covers: Literal["extraction"]
    requests: int
    input_tokens: int
    output_tokens: int
    usd: float


class FactsResponse(ApiModel):
    facts: list[Fact]
    unverified_ids: list[str]


class ValidateRequest(ApiModel):
    yaml: str = Field(max_length=1_000_000)
    strict: bool = False


class BankProblem(ApiModel):
    fact_id: str | None
    field: str | None
    reason: str


class ValidateResponse(ApiModel):
    valid: bool
    fact_count: int
    unverified_ids: list[str]
    problem: BankProblem | None


MAX_DISCOVERY_CAP = 200


class DiscoveryRefreshRequest(ApiModel):
    """Refresh the watched boards and score what survives, at most `cap` model calls."""

    backend: str = Field(min_length=1, max_length=100)
    confirm_hosted: bool = False
    cap: int | None = Field(default=None, ge=0, le=MAX_DISCOVERY_CAP)
    filters: ListingFilters = ListingFilters()


class BoardErrorResponse(ApiModel):
    ats: str
    slug: str
    reason: str


class DiscoverySummaryResponse(ApiModel):
    fetched: int
    blocked_boards: int
    filtered_out: dict[str, int]
    scored: int
    cache_hits: int
    unscored: int
    stopped_by: Literal["cap", "budget", "backend"] | None
    errors: list[BoardErrorResponse]


class RankedListingResponse(ApiModel):
    """One listing of the ranked list. The score is for triage, not a probability."""

    id: str
    title: str
    location: str
    ats: str
    slug: str
    urls: list[str]
    posted_at: datetime | None
    age_days: int | None
    status: Literal["scored", "no_score", "unscored"]
    score: float | None
    strong: int
    partial: int
    none: int
    incomplete: bool
    run_id: str | None


class DiscoveryListingsResponse(ApiModel):
    note: str
    listings: list[RankedListingResponse]
