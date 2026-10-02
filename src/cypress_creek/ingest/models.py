# ABOUTME: Pydantic models for the ingest stage: postings, requirements and typed warnings.
# ABOUTME: Requirement spans point into the normalized posting text.
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cypress_creek.facts.models import clean_issuer
from cypress_creek.ingest.hashing import text_hash as compute_text_hash
from cypress_creek.terms import normalize_term


class WarningKind(StrEnum):
    CONTROL_CHARS_STRIPPED = "control_chars_stripped"


class PostingWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: WarningKind
    count: int = Field(ge=1)


class PostingSource(StrEnum):
    PASTE = "paste"
    LINK = "link"
    PDF = "pdf"
    FEED = "feed"


class Extractor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Posting(BaseModel):
    """Normalized posting text. Hash and text are checked together so they cannot drift."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    source: PostingSource
    text: str = Field(min_length=1)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin_url: str | None = None
    extractor: Extractor
    warnings: list[PostingWarning] = []
    created_at: datetime

    @model_validator(mode="after")
    def _hash_matches_text(self) -> "Posting":
        if self.text_hash != compute_text_hash(self.text):
            raise ValueError("text_hash does not match the posting text")
        return self


class RequirementKind(StrEnum):
    SKILL = "skill"
    YEARS = "years"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    RESPONSIBILITY = "responsibility"
    SOFT = "soft"


class Importance(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    UNSPECIFIED = "unspecified"


class Requirement(BaseModel):
    """One requirement found in a posting. Whether text really is the posting's text at span,
    and whether importance fits the cue words, are checked by validators, not here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^R-\d+$")
    text: str = Field(min_length=1)
    span: tuple[int, int]
    kind: RequirementKind
    term: str
    years: int | None = Field(default=None, ge=1)
    issuer: str | None = None
    importance: Importance

    @field_validator("term")
    @classmethod
    def _normalize_term(cls, value: str) -> str:
        normalized = normalize_term(value)
        if not normalized:
            raise ValueError("term is empty after normalization")
        return normalized

    @field_validator("issuer")
    @classmethod
    def _clean_issuer(cls, value: str | None) -> str | None:
        return clean_issuer(value)

    @field_validator("span")
    @classmethod
    def _forward_range(cls, value: tuple[int, int]) -> tuple[int, int]:
        start, end = value
        if start < 0 or end <= start:
            raise ValueError("span must be a forward range starting at 0 or later")
        return value
