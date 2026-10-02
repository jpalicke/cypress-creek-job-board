# ABOUTME: Pydantic models for the fact bank: Fact, Tag, Evidence and the Bank container.
# ABOUTME: Verification is derived from verified_on, there is no separate boolean.
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cypress_creek.terms import normalize_term


class Kind(StrEnum):
    EMPLOYMENT = "employment"
    PROJECT = "project"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    ACHIEVEMENT = "achievement"


class Level(StrEnum):
    FAMILIAR = "familiar"
    WORKING = "working"
    EXPERT = "expert"


class EvidenceType(StrEnum):
    EMPLOYER_DOC = "employer_doc"
    REPO = "repo"
    CERTIFICATE = "certificate"
    PUBLIC_URL = "public_url"
    SELF_ATTESTED = "self_attested"


class Share(StrEnum):
    SHAREABLE = "shareable"
    LOCAL_ONLY = "local_only"


class Tag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    level: Level

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        normalized = normalize_term(value)
        if not normalized:
            raise ValueError("tag name is empty after normalization")
        return normalized


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: EvidenceType
    pointer: str = Field(min_length=1)


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: str = Field(pattern=r"^F-\d{4}$")
    claim: str = Field(min_length=1, max_length=300)
    kind: Kind
    employer: str | None = None
    role: str | None = None
    start: date | None = None
    end: date | None = None
    tags: list[Tag] = []
    verified_on: date | None = None
    evidence: Evidence
    share: Share = Share.LOCAL_ONLY

    @property
    def is_verified(self) -> bool:
        return self.verified_on is not None


class Bank(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: list[Fact]

    def verified_facts(self) -> list[Fact]:
        """The only view the pipeline may receive."""
        return [fact for fact in self.facts if fact.is_verified]

    def unverified_ids(self) -> list[str]:
        return [fact.id for fact in self.facts if not fact.is_verified]
