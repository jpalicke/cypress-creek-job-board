# ABOUTME: Stage 1 extraction: one model call, then only requirements found in the posting survive.
# ABOUTME: Code sets spans, ids and importance. A failed call is an incomplete result, not a guess.
import time
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from cypress_creek.ingest.models import Requirement
from cypress_creek.pipeline.prompt import Stage, build_prompt
from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.providers import (
    ContextTruncated,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
)
from cypress_creek.providers.base import Provider, Usage
from cypress_creek.providers.retry import RetryPolicy, call_with_retry
from cypress_creek.validators.cues import cue_importance
from cypress_creek.validators.requirements import MAX_REQUIREMENTS

MAX_DROPPED_TEXT = 200
MAX_OUTPUT_TOKENS = 4000
SCHEMA_VERSION = 1


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


class ExtractionStatus(StrEnum):
    OK = "ok"
    INCOMPLETE = "incomplete"


class ExtractionResult(BaseModel):
    """What stage 1 produced. Incomplete means the model call failed and nothing was extracted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ExtractionStatus
    requirements: list[Requirement]
    dropped: list[Dropped]
    not_assessed_count: int
    failure: str | None
    usage: Usage | None
    prompt_hash: str
    schema_version: int


FAILURE_LABELS: dict[type[ProviderError], str] = {
    SchemaViolation: "schema_violation",
    ContextTruncated: "context_truncated",
    ProviderUnavailable: "provider_unavailable",
    RateLimited: "rate_limited",
    Refusal: "refusal",
}


def failure_label(error: ProviderError) -> str | None:
    """The label for a provider failure that ends as an incomplete result, else None."""
    return FAILURE_LABELS.get(type(error))


def finish_extraction(
    posting_text: str, output: ExtractionOutput, prompt_hash: str, usage: Usage
) -> ExtractionResult:
    accepted = accept_proposals(posting_text, output)
    return ExtractionResult(
        status=ExtractionStatus.OK,
        requirements=accepted.requirements,
        dropped=accepted.dropped,
        not_assessed_count=accepted.not_assessed_count,
        failure=None,
        usage=usage,
        prompt_hash=prompt_hash,
        schema_version=SCHEMA_VERSION,
    )


def extract_requirements(
    posting_text: str,
    provider: Provider,
    *,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
) -> ExtractionResult:
    """Ask the model for requirements and accept only what the posting supports.

    A typed provider failure gives an incomplete result with no requirements. BudgetExceeded and
    any other error propagate, because a spent budget must stop the run.
    """
    capabilities = provider.capabilities
    prompt = build_prompt(Stage.EXTRACT, posting_text, [], capabilities, ExtractionOutput)

    def attempt(feedback: str | None) -> tuple[ExtractionOutput, Usage]:
        used = build_prompt(
            Stage.EXTRACT,
            posting_text,
            [],
            capabilities,
            ExtractionOutput,
            retry_feedback=feedback,
        )
        result = provider.complete_structured(
            used.system, used.data_block, ExtractionOutput, MAX_OUTPUT_TOKENS
        )
        return result.parsed, result.usage

    try:
        output, usage = call_with_retry(attempt, sleep=sleep, policy=policy)
    except ProviderError as error:
        label = failure_label(error)
        if label is None:
            raise
        return ExtractionResult(
            status=ExtractionStatus.INCOMPLETE,
            requirements=[],
            dropped=[],
            not_assessed_count=0,
            failure=label,
            usage=None,
            prompt_hash=prompt.prompt_hash,
            schema_version=SCHEMA_VERSION,
        )
    return finish_extraction(posting_text, output, prompt.prompt_hash, usage)
