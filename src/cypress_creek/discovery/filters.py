# ABOUTME: Deterministic listing filters (keywords, location, remote, seniority, age) with counts.
# ABOUTME: Cheap rejection before any model call. No model is consulted, and today is injected.
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cypress_creek.discovery.adapters.base import Listing
from cypress_creek.discovery.dedupe import fingerprint_text

# A title says the job is remote only in a bracket, after a dash or before one, as in
# "Engineer (Remote)", "Engineer - Remote" and "Remote - Engineer". The word alone inside a title
# can be part of the job, as in "Remote Sensing Engineer".
_REMOTE_IN_TITLE = re.compile(
    r"[(\[][^)\]]*\bremote\b[^)\]]*[)\]]|[-\u2013\u2014|:]\s*remote\s*$|^\s*remote\s*[-\u2013\u2014|:]"
)


class FilterName(StrEnum):
    """The filters in the order they are tried. A listing is counted under the first that fails."""

    AGE = "age"
    LOCATION = "location"
    REMOTE = "remote"
    SENIORITY = "seniority"
    EXCLUDE = "exclude"
    INCLUDE = "include"


class ListingFilters(BaseModel):
    """What to keep. An empty or unset field applies no filter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    remote: bool | None = None
    exclude_seniority: tuple[str, ...] = ()
    max_age_days: int | None = Field(default=None, ge=1)

    @field_validator("include_keywords", "exclude_keywords", "locations", "exclude_seniority")
    @classmethod
    def _terms_must_have_words(cls, terms: tuple[str, ...]) -> tuple[str, ...]:
        for term in terms:
            if not fingerprint_text(term):
                raise ValueError("a filter term needs at least one word")
        return terms


@dataclass(frozen=True)
class FilterReport:
    """The listings kept and, for every filter, how many listings it was the first to remove."""

    kept: tuple[Listing, ...]
    removed: dict[FilterName, int]

    @property
    def total_removed(self) -> int:
        return sum(self.removed.values())


def apply_filters(
    listings: Sequence[Listing], filters: ListingFilters, today: date
) -> FilterReport:
    """Keep the listings that pass every filter, in input order, and count the removals."""
    removed = {name: 0 for name in FilterName}
    kept: list[Listing] = []
    for listing in listings:
        failed = _first_failure(listing, filters, today)
        if failed is None:
            kept.append(listing)
        else:
            removed[failed] += 1
    return FilterReport(kept=tuple(kept), removed=removed)


def _first_failure(listing: Listing, filters: ListingFilters, today: date) -> FilterName | None:
    title = fingerprint_text(listing.title)
    location = fingerprint_text(listing.location)
    text = f"{title} {fingerprint_text(listing.content_text)}"
    if (
        filters.max_age_days is not None
        and listing.posted_at is not None
        and (today - listing.posted_at.date()).days > filters.max_age_days
    ):
        return FilterName.AGE
    if filters.locations and not _has_any(location, filters.locations):
        return FilterName.LOCATION
    if filters.remote is not None and _is_remote(listing, location) != filters.remote:
        return FilterName.REMOTE
    if _has_any(title, filters.exclude_seniority):
        return FilterName.SENIORITY
    if _has_any(text, filters.exclude_keywords):
        return FilterName.EXCLUDE
    if filters.include_keywords and not _has_any(text, filters.include_keywords):
        return FilterName.INCLUDE
    return None


def _is_remote(listing: Listing, location: str) -> bool:
    """Whether the location says remote, or the title does in one of its marked forms."""
    return _has_any(location, ("remote",)) or bool(
        _REMOTE_IN_TITLE.search(unicodedata.normalize("NFKC", listing.title).casefold())
    )


def _has_any(normalized_text: str, terms: Sequence[str]) -> bool:
    """Whether any term occurs in the text as whole words. Both sides are fingerprint text."""
    padded = f" {normalized_text} "
    return any(f" {fingerprint_text(term)} " in padded for term in terms)
