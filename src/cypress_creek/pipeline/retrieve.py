# ABOUTME: Stage 2 retrieval: finds candidate facts per requirement by tags and aliases, no model.
# ABOUTME: A requirement with no candidate is a gap at once, and the support ceiling is set here.
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Bank, Fact, Level
from cypress_creek.ingest.models import Requirement
from cypress_creek.pipeline.prompt import prompt_facts
from cypress_creek.providers.base import Capabilities
from cypress_creek.scoring.aliases import AliasTable
from cypress_creek.scoring.support import Gate, Support, candidate_facts, support_ceiling

MAX_CANDIDATES = 5
_LEVEL_STRENGTH = {Level.FAMILIAR: 0, Level.WORKING: 1, Level.EXPERT: 2}


class RequirementCandidates(BaseModel):
    """The facts later stages may weigh for one requirement, and the most support they can give."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    fact_ids: list[str]
    dropped_count: int
    support: Support
    gate: Gate

    @property
    def is_gap(self) -> bool:
        return not self.fact_ids


def _strength(requirement: Requirement, fact: Fact, aliases: AliasTable) -> int:
    wanted = aliases.canonical(requirement.term)
    return max(
        _LEVEL_STRENGTH[tag.level] for tag in fact.tags if aliases.canonical(tag.name) == wanted
    )


def _recency(fact: Fact) -> date:
    """An open role ends today, so it sorts as the most recent. No dates sorts last."""
    return fact.end or date.max if fact.start is not None else date.min


def _ranked(
    requirement: Requirement, candidates: Sequence[Fact], aliases: AliasTable
) -> list[Fact]:
    """Strongest tag level first, then most recent, then fact id so the order never varies."""
    return sorted(
        candidates,
        key=lambda fact: (
            -_strength(requirement, fact, aliases),
            -_recency(fact).toordinal(),
            fact.id,
        ),
    )


def retrieve(
    requirements: Sequence[Requirement],
    bank: Bank,
    capabilities: Capabilities,
    today: date,
    aliases: AliasTable,
) -> list[RequirementCandidates]:
    """Candidates and a support ceiling for each requirement, in input order.

    Only verified facts are used, and `local_only` facts are left out for a hosted backend.
    The ceiling is computed from every matching fact. The cap only limits what later stages see.
    """
    visible = prompt_facts(bank.verified_facts(), capabilities)
    results: list[RequirementCandidates] = []
    for requirement in requirements:
        matching = candidate_facts(requirement, visible, aliases)
        support, gate = support_ceiling(requirement, matching, today, aliases)
        ranked = _ranked(requirement, matching, aliases)
        results.append(
            RequirementCandidates(
                requirement_id=requirement.id,
                fact_ids=[fact.id for fact in ranked[:MAX_CANDIDATES]],
                dropped_count=max(0, len(ranked) - MAX_CANDIDATES),
                support=support,
                gate=gate,
            )
        )
    return results
