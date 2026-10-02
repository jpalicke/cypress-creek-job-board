# ABOUTME: Accepts proposed requirements from the extraction model: only text found in the posting.
# ABOUTME: Code sets spans, ids and importance, drops the rest with a reason, and caps the count.
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from cypress_creek.ingest.models import Requirement
from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.validators.cues import cue_importance
from cypress_creek.validators.requirements import MAX_REQUIREMENTS

MAX_DROPPED_TEXT = 200


class DropReason(StrEnum):
    TEXT_NOT_IN_POSTING = "text_not_in_posting"
    DUPLICATE_TERM = "duplicate_term"
    INVALID_FIELD = "invalid_field"


class Dropped(BaseModel):
    """A proposal that was not kept. The text is shortened, it is model output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    reason: DropReason


class Acceptance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirements: list[Requirement]
    dropped: list[Dropped]
    not_assessed_count: int


def _locate(posting_text: str, text: str, used: list[tuple[int, int]]) -> tuple[int, int] | None:
    """The first occurrence of text that no earlier requirement already claimed."""
    start = posting_text.find(text)
    while start != -1:
        end = start + len(text)
        if not any(start < used_end and used_start < end for used_start, used_end in used):
            return start, end
        start = posting_text.find(text, start + 1)
    return None


def accept_proposals(posting_text: str, output: ExtractionOutput) -> Acceptance:
    """Keep the proposals whose text is in the posting. Everything else about them is derived."""
    requirements: list[Requirement] = []
    dropped: list[Dropped] = []
    used: list[tuple[int, int]] = []
    seen_terms: set[str] = set()
    not_assessed = 0
    for proposal in output.requirements:
        shown = proposal.text[:MAX_DROPPED_TEXT]
        span = _locate(posting_text, proposal.text, used) if proposal.text else None
        if span is None:
            dropped.append(Dropped(text=shown, reason=DropReason.TEXT_NOT_IN_POSTING))
            continue
        try:
            requirement = Requirement(
                id=f"R-{len(requirements) + 1}",
                text=proposal.text,
                span=span,
                kind=proposal.kind,
                term=proposal.term,
                years=proposal.years,
                issuer=proposal.issuer,
                importance=cue_importance(posting_text, span),
            )
        except ValidationError:
            dropped.append(Dropped(text=shown, reason=DropReason.INVALID_FIELD))
            continue
        if requirement.term in seen_terms:
            dropped.append(Dropped(text=shown, reason=DropReason.DUPLICATE_TERM))
            continue
        if len(requirements) >= MAX_REQUIREMENTS:
            not_assessed += 1
            continue
        seen_terms.add(requirement.term)
        used.append(span)
        requirements.append(requirement)
    return Acceptance(requirements=requirements, dropped=dropped, not_assessed_count=not_assessed)
