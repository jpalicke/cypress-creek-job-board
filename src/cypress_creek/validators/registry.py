# ABOUTME: The catalogue of validators V1 to V14: id, name, rule and the function that checks it.
# ABOUTME: The eval harness looks validators up here so it runs exactly what production runs.
from collections.abc import Callable
from dataclasses import dataclass

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
)
