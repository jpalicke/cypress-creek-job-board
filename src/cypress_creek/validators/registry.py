# ABOUTME: The catalogue of validators V1 to V14: id, name, rule and the function that checks it.
# ABOUTME: The eval harness looks validators up here so it runs exactly what production runs.
from collections.abc import Callable
from dataclasses import dataclass

from cypress_creek.validators.citations import (
    check_fact_exists,
    check_fact_shareable,
    check_fact_verified,
)
from cypress_creek.validators.claims import check_citation_required, check_novel_terms
from cypress_creek.validators.consistency import check_entities, check_numbers
from cypress_creek.validators.extraction import check_importance, check_schema, check_verbatim_span
from cypress_creek.validators.verdict import Verdict


@dataclass(frozen=True)
class ValidatorInfo:
    id: str
    name: str
    rule: str
    check: Callable[..., Verdict]


def _catalogue(*entries: tuple[str, str, str, Callable[..., Verdict]]) -> dict[str, ValidatorInfo]:
    return {entry[0]: ValidatorInfo(*entry) for entry in entries}


REGISTRY: dict[str, ValidatorInfo] = _catalogue(
    ("V1", "Schema", "Output parses and conforms to the model, no extra fields.", check_schema),
    (
        "V2",
        "Verbatim span",
        "Requirement text equals the posting at its span.",
        check_verbatim_span,
    ),
    (
        "V3",
        "Importance cues",
        "Importance agrees with the cue words near the span.",
        check_importance,
    ),
    ("V4", "Fact exists", "Every cited ID is in the bank.", check_fact_exists),
    ("V5", "Fact verified", "Every cited fact has verified_on.", check_fact_verified),
    (
        "V6",
        "Fact shareable",
        "No local_only fact was sent to, or cited from, a hosted backend.",
        check_fact_shareable,
    ),
    (
        "V7",
        "Entity consistency",
        "Dates match a cited fact and no uncited fact's employer or role is named.",
        check_entities,
    ),
    (
        "V8",
        "Numeric consistency",
        "Every number appears in a cited fact or in the requirement it answers.",
        check_numbers,
    ),
    ("V9", "Citation required", "Every claim cites at least one fact ID.", check_citation_required),
    (
        "V10",
        "Novel term flag",
        "Terms absent from the cited facts and the requirement are flagged (heuristic).",
        check_novel_terms,
    ),
)
