# ABOUTME: Stage 3 entailment: the model verdict can confirm or lower the rule ceiling, never raise.
# ABOUTME: Citations and the rationale are checked by validators. A failed call keeps the ceiling.
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Bank, Fact
from cypress_creek.ingest.models import Requirement
from cypress_creek.pipeline.extract import failure_label
from cypress_creek.pipeline.prompt import Prompt, Stage, build_prompt, prompt_facts
from cypress_creek.pipeline.retrieve import RequirementCandidates
from cypress_creek.pipeline.schemas import EntailmentOutput, EntailmentVerdict
from cypress_creek.providers import ProviderError
from cypress_creek.providers.base import Capabilities, Provider, Usage
from cypress_creek.providers.retry import RetryPolicy, call_with_retry
from cypress_creek.scoring.score import Match, lowest
from cypress_creek.scoring.support import Support
from cypress_creek.validators.citations import (
    check_fact_exists,
    check_fact_shareable,
    check_fact_verified,
)
from cypress_creek.validators.claims import check_citation_required, check_novel_terms
from cypress_creek.validators.consistency import check_entities, check_numbers

ENTAIL_MAX_OUTPUT_TOKENS = 500
RATIONALE_WITHHELD = "rationale withheld: failed grounding check"

_VERDICT_SUPPORT = {
    EntailmentVerdict.SUPPORTS: Support.STRONG,
    EntailmentVerdict.PARTIAL: Support.PARTIAL,
    EntailmentVerdict.DOES_NOT_SUPPORT: Support.NONE,
}


class Entailment(StrEnum):
    """What the second opinion did. Not run means the support is the rule ceiling alone."""

    CONFIRMED = "confirmed"
    DOWNGRADED = "downgraded"
    NOT_RUN = "not_run"
    NOT_NEEDED = "not_needed"


class EntailedMatch(BaseModel):
    """A requirement's final support with what the entailment stage did to reach it.

    `rationale` is display text only and never changes support. `raise_attempted` counts a
    verdict above the ceiling that the clamp ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    match: Match
    entailment: Entailment
    fact_ids: list[str]
    rationale: str | None
    raise_attempted: bool
    failure: str | None = None
    usage: Usage | None = None
    prompt_hash: str | None = None


@dataclass(frozen=True)
class _Claim:
    text: str
    fact_ids: list[str]


def _valid_citations(
    cited: Sequence[str], candidate_ids: Sequence[str], bank: Bank, capabilities: Capabilities
) -> list[str]:
    """Cited ids that were sent to the model and pass V4, V5 and V6, each once, in cited order."""
    sent = set(candidate_ids)
    return [
        fact_id
        for fact_id in dict.fromkeys(cited)
        if fact_id in sent
        and check_fact_exists([fact_id], bank).passed
        and check_fact_verified([fact_id], bank).passed
        and check_fact_shareable([fact_id], bank, hosted=not capabilities.local).passed
    ]


def _rationale_is_grounded(
    text: str, cited: Sequence[Fact], requirement: Requirement, bank: Bank, *, positive: bool
) -> bool:
    """V7, V8 and V10 on the text. A positive verdict's rationale also needs a citation (V9)."""
    verdicts = [
        check_entities(text, cited, bank),
        check_numbers(text, cited, requirement.text),
        check_novel_terms(text, cited, requirement.text),
    ]
    if positive:
        verdicts.append(check_citation_required([_Claim(text, [fact.id for fact in cited])]))
    return all(verdict.passed for verdict in verdicts)


def judge(
    output: EntailmentOutput,
    requirement: Requirement,
    candidate_ids: Sequence[str],
    ceiling: Support,
    bank: Bank,
    capabilities: Capabilities,
) -> EntailedMatch:
    """Apply the model's answer to the ceiling. Pure: every rule of the stage is decided here.

    Support is the lower of the ceiling and the verdict. A positive verdict with no valid
    citation counts as does_not_support, because a model that shows no fact has shown nothing."""
    valid = _valid_citations(output.fact_ids, candidate_ids, bank, capabilities)
    claimed = _VERDICT_SUPPORT[output.verdict]
    uncited = claimed is not Support.NONE and not valid
    proposed = Support.NONE if uncited else claimed
    support = lowest(proposed, ceiling)

    by_id = {fact.id: fact for fact in bank.facts}
    cited = [by_id[fact_id] for fact_id in valid]
    text = output.rationale.strip()
    rationale: str | None
    if not text:
        rationale = None
    elif uncited or not _rationale_is_grounded(
        text, cited, requirement, bank, positive=claimed is not Support.NONE
    ):
        rationale = RATIONALE_WITHHELD
    else:
        rationale = text

    return EntailedMatch(
        match=Match(
            requirement_id=requirement.id,
            importance=requirement.importance,
            ceiling=ceiling,
            support=support,
        ),
        entailment=Entailment.CONFIRMED if support is ceiling else Entailment.DOWNGRADED,
        fact_ids=valid,
        rationale=rationale,
        raise_attempted=lowest(claimed, ceiling) is not claimed,
    )


def entail_cap(capabilities: Capabilities) -> int:
    """Room for a short verdict: at most half the window, so a small window still has room."""
    return min(ENTAIL_MAX_OUTPUT_TOKENS, capabilities.context_tokens // 2)


def entail(
    requirement: Requirement,
    candidates: RequirementCandidates,
    bank: Bank,
    provider: Provider,
    *,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
) -> EntailedMatch:
    """Ask the model once whether the candidate facts support the requirement, then judge it.

    A requirement with no candidate is a gap and makes no call. A typed provider failure keeps
    the rule ceiling and is marked not run. BudgetExceeded and any other error propagate.
    """
    ceiling = candidates.support
    capabilities = provider.capabilities
    if candidates.is_gap:
        return _unjudged(requirement, ceiling, Entailment.NOT_NEEDED)
    by_id = {fact.id: fact for fact in bank.facts}
    shown = prompt_facts([by_id[fact_id] for fact_id in candidates.fact_ids], capabilities)

    def build(feedback: str | None = None) -> Prompt:
        return build_prompt(
            Stage.ENTAIL,
            requirement.text,
            shown,
            capabilities,
            EntailmentOutput,
            retry_feedback=feedback,
        )

    def attempt(feedback: str | None) -> tuple[EntailmentOutput, Usage]:
        used = build(feedback)
        result = provider.complete_structured(
            used.system, used.user_message, EntailmentOutput, entail_cap(capabilities)
        )
        return result.parsed, result.usage

    prompt_hash = build().prompt_hash
    try:
        output, usage = call_with_retry(attempt, sleep=sleep, policy=policy)
    except ProviderError as error:
        label = failure_label(error)
        if label is None:
            raise
        return _unjudged(requirement, ceiling, Entailment.NOT_RUN, label, prompt_hash)
    judged = judge(output, requirement, candidates.fact_ids, ceiling, bank, capabilities)
    return judged.model_copy(update={"usage": usage, "prompt_hash": prompt_hash})


def _unjudged(
    requirement: Requirement,
    ceiling: Support,
    entailment: Entailment,
    failure: str | None = None,
    prompt_hash: str | None = None,
) -> EntailedMatch:
    """The rule ceiling as the support, for a requirement the model did not weigh in on."""
    return EntailedMatch(
        match=Match(
            requirement_id=requirement.id,
            importance=requirement.importance,
            ceiling=ceiling,
            support=ceiling,
        ),
        entailment=entailment,
        fact_ids=[],
        rationale=None,
        raise_attempted=False,
        failure=failure,
        prompt_hash=prompt_hash,
    )
