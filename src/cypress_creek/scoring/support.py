# ABOUTME: Deterministic support gate: finds candidate facts for a requirement and sets a ceiling.
# ABOUTME: A model verdict may later confirm or downgrade this ceiling, never raise it.
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Protocol

from cypress_creek.facts.models import Fact, Kind, Level
from cypress_creek.scoring.aliases import AliasTable
from cypress_creek.storage.company_key import company_key

DAYS_PER_YEAR = 365.25
_NO_ALIASES = AliasTable({})


class Support(StrEnum):
    NONE = "none"
    PARTIAL = "partial"
    STRONG = "strong"


class Gate(StrEnum):
    """The rule that decided the ceiling."""

    NO_CANDIDATE = "no_candidate"
    FAMILIAR_LEVEL = "familiar_level"
    NO_DATES = "no_dates"
    YEARS_BELOW = "years_below"
    YEARS_MET = "years_met"
    TERM_MATCH = "term_match"


class SupportRequirement(Protocol):
    """The parts of a requirement the gate reads. The ingest Requirement model satisfies it."""

    @property
    def term(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def years(self) -> int | None: ...
    @property
    def issuer(self) -> str | None: ...


# Education and certification requirements only match facts of that kind.
_ENTITY_KINDS = {"education": Kind.EDUCATION, "certification": Kind.CERTIFICATION}


def _matching_levels(
    requirement: SupportRequirement, fact: Fact, aliases: AliasTable
) -> list[Level]:
    wanted = aliases.canonical(requirement.term)
    return [tag.level for tag in fact.tags if aliases.canonical(tag.name) == wanted]


def _kind_allowed(requirement: SupportRequirement, fact: Fact) -> bool:
    required_kind = _ENTITY_KINDS.get(requirement.kind)
    if required_kind is not None:
        return fact.kind == required_kind and _issuer_allowed(requirement, fact)
    return fact.kind not in _ENTITY_KINDS.values()


def _issuer_allowed(requirement: SupportRequirement, fact: Fact) -> bool:
    """A requirement that names an issuer is met only by a fact from the same issuer."""
    if requirement.issuer is None:
        return True
    return fact.issuer is not None and company_key(fact.issuer) == company_key(requirement.issuer)


def candidate_facts(
    requirement: SupportRequirement, facts: Sequence[Fact], aliases: AliasTable
) -> list[Fact]:
    """Facts with a tag equal to the requirement term or one of its aliases."""
    return [
        fact
        for fact in facts
        if _kind_allowed(requirement, fact) and _matching_levels(requirement, fact, aliases)
    ]


def merged_years(facts: Sequence[Fact], today: date) -> float:
    """Years covered by the facts' date intervals, overlaps counted once. Open roles end today."""
    intervals = sorted((fact.start, fact.end or today) for fact in facts if fact.start is not None)
    total_days = 0
    current_start: date | None = None
    current_end: date | None = None
    for start, end in intervals:
        if current_end is None or start > current_end:
            if current_start is not None and current_end is not None:
                total_days += (current_end - current_start).days
            current_start, current_end = start, end
        elif end > current_end:
            current_end = end
    if current_start is not None and current_end is not None:
        total_days += (current_end - current_start).days
    return total_days / DAYS_PER_YEAR


def support_ceiling(
    requirement: SupportRequirement,
    candidates: Sequence[Fact],
    today: date,
    aliases: AliasTable = _NO_ALIASES,
) -> tuple[Support, Gate]:
    """The most support the candidates can ever justify, and the rule that decided it."""
    if not candidates:
        return Support.NONE, Gate.NO_CANDIDATE
    levels = [lvl for fact in candidates for lvl in _matching_levels(requirement, fact, aliases)]
    if levels and all(level == Level.FAMILIAR for level in levels):
        return Support.PARTIAL, Gate.FAMILIAR_LEVEL
    if requirement.years is None or requirement.kind in _ENTITY_KINDS:
        return Support.STRONG, Gate.TERM_MATCH
    held = merged_years(candidates, today)
    if held == 0:
        return Support.PARTIAL, Gate.NO_DATES
    if held >= requirement.years:
        return Support.STRONG, Gate.YEARS_MET
    return Support.PARTIAL, Gate.YEARS_BELOW
