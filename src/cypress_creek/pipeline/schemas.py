# ABOUTME: The shapes the models must answer in: proposed requirements and an entailment verdict.
# ABOUTME: Strict, so an unknown field or another schema version fails the V1 schema check.
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cypress_creek.ingest.models import Importance, RequirementKind


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
