# ABOUTME: The shape the extraction model must answer in: proposed requirements, no offsets.
# ABOUTME: Strict, so an unknown field or another schema version fails the V1 schema check.
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
