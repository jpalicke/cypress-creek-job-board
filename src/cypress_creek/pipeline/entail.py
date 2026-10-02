# ABOUTME: Stage 3 entailment: the model verdict can confirm or lower the rule ceiling, never raise.
# ABOUTME: Citations and the rationale are checked by validators. A failed call keeps the ceiling.
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Bank, Fact
from cypress_creek.ingest.models import Requirement
from cypress_creek.pipeline.schemas import EntailmentOutput, EntailmentVerdict
from cypress_creek.providers.base import Capabilities, Usage
from cypress_creek.scoring.score import Match, lowest
from cypress_creek.scoring.support import Support
from cypress_creek.validators.citations import (
    check_fact_exists,
    check_fact_shareable,
    check_fact_verified,
)
from cypress_creek.validators.claims import check_citation_required, check_novel_terms
from cypress_creek.validators.consistency import check_entities, check_numbers

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
