# ABOUTME: The shapes the models must answer in: proposed requirements and an entailment verdict.
# ABOUTME: Strict, so an unknown field or another schema version fails the V1 schema check.
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cypress_creek.facts.models import Kind
from cypress_creek.ingest.models import Importance, RequirementKind

MAX_DRAFT_SENTENCES = 5
MAX_DRAFT_SENTENCE_CHARS = 300
MAX_CANDIDATES = 40
MAX_CANDIDATE_TAGS = 8
MAX_SOURCE_CHARS = 1000


class ProposedRequirement(BaseModel):
    """What the model claims about one requirement. Code finds the span and sets the id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    kind: RequirementKind
    term: str
    years: int | None = None
    issuer: str | None = None
    importance: Importance


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    requirements: list[ProposedRequirement]


class EntailmentVerdict(StrEnum):
    SUPPORTS = "supports"
    PARTIAL = "partial"
    DOES_NOT_SUPPORT = "does_not_support"


class EntailmentOutput(BaseModel):
    """The model's second opinion on one requirement. Code decides what, if anything, it changes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    verdict: EntailmentVerdict
    fact_ids: list[str]
    rationale: str


class DraftSentenceOutput(BaseModel):
    """One sentence of draft help and the fact IDs the model says it paraphrases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(max_length=MAX_DRAFT_SENTENCE_CHARS)
    fact_ids: list[str]


class DraftOutput(BaseModel):
    """A short draft for one requirement. Every sentence is checked before a person sees it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    sentences: list[DraftSentenceOutput] = Field(max_length=MAX_DRAFT_SENTENCES)


class ResumeCandidate(BaseModel):
    """One fact the model proposes from a resume. It has no level, no dates and no employer
    fields: those are judgements or details the person adds when they review the fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str = Field(max_length=300)
    kind: Kind
    tags: list[str] = Field(max_length=MAX_CANDIDATE_TAGS)
    source: str = Field(max_length=MAX_SOURCE_CHARS)


class ResumeImportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    candidates: list[ResumeCandidate] = Field(max_length=MAX_CANDIDATES)
