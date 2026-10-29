# ABOUTME: Draft help: a short paraphrase of verified facts for a requirement, checked per sentence.
# ABOUTME: It only returns data. Nothing is sent, copied or applied; a person reviews every line.
import time
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Requirement
from cypress_creek.pipeline.extract import failure_label
from cypress_creek.pipeline.prompt import Prompt, Stage, build_prompt, prompt_facts
from cypress_creek.pipeline.retrieve import RequirementCandidates
from cypress_creek.pipeline.schemas import DraftOutput, DraftSentenceOutput
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import ProviderError
from cypress_creek.providers.base import Capabilities, Provider, Usage
from cypress_creek.providers.retry import RetryPolicy, call_with_retry
from cypress_creek.scoring.support import Support
from cypress_creek.validators.citations import (
    check_fact_exists,
    check_fact_shareable,
    check_fact_verified,
)
from cypress_creek.validators.claims import check_citation_required, check_novel_terms
from cypress_creek.validators.consistency import check_entities, check_numbers
from cypress_creek.validators.verdict import Verdict

DRAFT_MAX_OUTPUT_TOKENS = 600
SCHEMA_VERSION = 1
NO_SUPPORT_MESSAGE = "no verified fact supports this"
NO_SUPPORT_ADVICE = (
    "If you really have this experience, add a verified fact for it to your fact bank "
    "and ask again."
)
REVIEW_BANNER = (
    "DRAFT FOR HUMAN REVIEW. Nothing here is sent anywhere. "
    "Check every line against your own record before you copy it."
)
DETAIL_LIMIT = 60

# V8 and V10 accept the requirement text as an extra source, which suits a rationale that talks
# about the requirement. A draft is a claim about the candidate and the posting is hostile input,
# so its numbers and terms may come from the cited facts alone.
NO_EXTRA_TEXT = ""


class DraftStatus(StrEnum):
    DRAFTED = "drafted"
    NO_SUPPORT = "no_support"
    NOT_RUN = "not_run"


class DraftSentence(BaseModel):
    """A drafted sentence with the verdicts of every check. It is clean only if all passed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    fact_ids: list[str]
    verdicts: list[Verdict]

    @property
    def passed(self) -> bool:
        return all(verdict.passed for verdict in self.verdicts)


class Draft(BaseModel):
    """Draft help for one requirement. `needs_human_review` is always true: a person reads it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    requirement_text: str
    status: DraftStatus
    sentences: list[DraftSentence]
    needs_human_review: Literal[True] = True
    failure: str | None = None
    usage: Usage | None = None
    prompt_hash: str | None = None

    @property
    def clean_sentences(self) -> list[str]:
        """The text of the sentences that passed every check, the only ones fit to copy."""
        return [sentence.text for sentence in self.sentences if sentence.passed]


class _Claim:
    def __init__(self, text: str, fact_ids: Sequence[str]) -> None:
        self.text = text
        self.fact_ids = fact_ids


def _judge_sentence(
    sentence: DraftSentenceOutput,
    supplied_ids: Sequence[str],
    bank: Bank,
    capabilities: Capabilities,
) -> DraftSentence:
    """Run every check on one sentence. None short circuits, so the record is complete.

    V4 is checked against the facts that were supplied, so a real fact the model was never
    shown cannot be cited."""
    cited_ids = list(dict.fromkeys(sentence.fact_ids))
    supplied = Bank(facts=[fact for fact in bank.facts if fact.id in set(supplied_ids)])
    by_id = {fact.id: fact for fact in bank.facts}
    cited = [by_id[fact_id] for fact_id in cited_ids if fact_id in by_id]
    verdicts = [
        check_fact_exists(cited_ids, supplied),
        check_fact_verified(cited_ids, bank),
        check_fact_shareable(cited_ids, bank, hosted=not capabilities.local),
        check_entities(sentence.text, cited, bank),
        check_numbers(sentence.text, cited, NO_EXTRA_TEXT),
        check_citation_required([_Claim(sentence.text, cited_ids)]),
        check_novel_terms(sentence.text, cited, NO_EXTRA_TEXT, closed_vocabulary=True),
    ]
    return DraftSentence(
        text=sentence.text.strip(), fact_ids=cited_ids, verdicts=sorted(verdicts, key=_by_number)
    )


def _by_number(verdict: Verdict) -> int:
    return int(verdict.validator.removeprefix("V"))


def judge_draft(
    output: DraftOutput,
    requirement: Requirement,
    supplied_ids: Sequence[str],
    bank: Bank,
    capabilities: Capabilities,
    *,
    trace: PipelineTrace | None = None,
) -> Draft:
    """Check each sentence of the model's draft. Pure: every rule of the stage is decided here.

    A sentence that fails any check stays in the result with its verdicts, so it can be shown
    with a warning, but it is never part of `clean_sentences`."""
    sentences = [
        _judge_sentence(sentence, supplied_ids, bank, capabilities)
        for sentence in output.sentences
        if sentence.text.strip()
    ]
    if trace is not None:
        for sentence in sentences:
            for verdict in sentence.verdicts:
                trace.record_validator(Stage.DRAFT, requirement.id, verdict)
    if not sentences:
        return _unwritten(requirement, DraftStatus.NOT_RUN, "empty_draft")
    return Draft(
        requirement_id=requirement.id,
        requirement_text=requirement.text,
        status=DraftStatus.DRAFTED,
        sentences=sentences,
    )


def draft_cap(capabilities: Capabilities) -> int:
    """Room for a few sentences: at most half the window, so a small window still has room."""
    return min(DRAFT_MAX_OUTPUT_TOKENS, capabilities.context_tokens // 2)


def draft(
    requirement: Requirement,
    candidates: RequirementCandidates,
    bank: Bank,
    provider: Provider,
    *,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
    trace: PipelineTrace | None = None,
) -> Draft:
    """Ask the model once for a short draft from the candidate facts, then check every sentence.

    A requirement the report found no support for is never drafted and makes no call. A typed
    provider failure is `not_run`. BudgetExceeded and any other error propagate."""
    if candidates.is_gap or candidates.support is Support.NONE:
        return _unwritten(requirement, DraftStatus.NO_SUPPORT)
    capabilities = provider.capabilities
    by_id = {fact.id: fact for fact in bank.facts}
    shown = prompt_facts([by_id[fact_id] for fact_id in candidates.fact_ids], capabilities)

    def build(feedback: str | None = None) -> Prompt:
        return build_prompt(
            Stage.DRAFT, requirement.text, shown, capabilities, DraftOutput, retry_feedback=feedback
        )

    def attempt(feedback: str | None) -> tuple[DraftOutput, Usage]:
        used = build(feedback)
        try:
            result = provider.complete_structured(
                used.system, used.user_message, DraftOutput, draft_cap(capabilities)
            )
        except ProviderError as error:
            if trace is not None and error.request_attempted:
                trace.record_call(
                    stage=Stage.DRAFT,
                    prompt_hash=used.prompt_hash,
                    schema_version=SCHEMA_VERSION,
                    usage=error.usage,
                    cost_per_mtok=capabilities.cost_per_mtok,
                    error_type=type(error).__name__,
                )
            raise
        if trace is not None:
            trace.record_call(
                stage=Stage.DRAFT,
                prompt_hash=used.prompt_hash,
                schema_version=SCHEMA_VERSION,
                usage=result.usage,
                cost_per_mtok=capabilities.cost_per_mtok,
            )
        return result.parsed, result.usage

    prompt_hash = build().prompt_hash
    try:
        output, usage = call_with_retry(attempt, sleep=sleep, policy=policy)
    except ProviderError as error:
        label = failure_label(error)
        if label is None:
            raise
        return _unwritten(requirement, DraftStatus.NOT_RUN, label, prompt_hash)
    judged = judge_draft(
        output, requirement, [fact.id for fact in shown], bank, capabilities, trace=trace
    )
    return judged.model_copy(update={"usage": usage, "prompt_hash": prompt_hash})


def _unwritten(
    requirement: Requirement,
    status: DraftStatus,
    failure: str | None = None,
    prompt_hash: str | None = None,
) -> Draft:
    return Draft(
        requirement_id=requirement.id,
        requirement_text=requirement.text,
        status=status,
        sentences=[],
        failure=failure,
        prompt_hash=prompt_hash,
    )


def _one_line(text: str, limit: int | None = None) -> str:
    flat = " ".join(text.split())
    return flat if limit is None or len(flat) <= limit else flat[: limit - 1] + "..."


def _warning(sentence: DraftSentence) -> str:
    reasons = [
        f"{v.validator}: {v.reason}"
        + (f" ({_one_line(v.offending, DETAIL_LIMIT)})" if v.offending else "")
        for v in sentence.verdicts
        if not v.passed
    ]
    return "; ".join(reasons)


def render_draft(result: Draft) -> str:
    """Plain text for a person. Failed sentences are marked and never look like clean ones, and
    model text is flattened to one line so it cannot forge a line or a banner."""
    lines = [
        REVIEW_BANNER,
        f"Requirement {result.requirement_id}: {_one_line(result.requirement_text)}",
    ]
    if result.status is DraftStatus.NO_SUPPORT:
        lines += [f"{NO_SUPPORT_MESSAGE}.", NO_SUPPORT_ADVICE]
    elif result.status is DraftStatus.NOT_RUN:
        lines.append(f"No draft was produced ({result.failure}).")
    else:
        for sentence in result.sentences:
            cites = ", ".join(sentence.fact_ids) or "no fact"
            text = f"{_one_line(sentence.text)} [{cites}]"
            if sentence.passed:
                lines.append(f"  - {text}")
            else:
                lines.append(f"  ! NOT VERIFIED ({_warning(sentence)}): {text}")
        if not result.clean_sentences:
            lines.append("No sentence passed every check. Do not use this draft.")
    return "\n".join(lines)
