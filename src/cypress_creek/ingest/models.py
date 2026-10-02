# ABOUTME: Pydantic models for the ingest stage: postings, requirements and typed warnings.
# ABOUTME: Requirement spans point into the normalized posting text.
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WarningKind(StrEnum):
    CONTROL_CHARS_STRIPPED = "control_chars_stripped"


class PostingWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: WarningKind
    count: int = Field(ge=1)
