# ABOUTME: Tests the shape the entailment model must answer in: a verdict, cited ids, a rationale.
# ABOUTME: Strict, so an unknown field, an unknown verdict or another schema version is refused.
from typing import Any

import pytest
from pydantic import ValidationError

from cypress_creek.pipeline.schemas import EntailmentOutput, EntailmentVerdict

VALID: dict[str, Any] = {
    "schema_version": 1,
    "verdict": "supports",
    "fact_ids": ["F-0001"],
    "rationale": "Fact F-0001 shows the work.",
}


def test_a_valid_answer_parses() -> None:
    output = EntailmentOutput.model_validate(VALID)
    assert output.verdict is EntailmentVerdict.SUPPORTS
    assert output.fact_ids == ["F-0001"]


@pytest.mark.parametrize("verdict", ["supports", "partial", "does_not_support"])
def test_each_published_verdict_is_accepted(verdict: str) -> None:
    assert EntailmentOutput.model_validate({**VALID, "verdict": verdict}).verdict.value == verdict


@pytest.mark.parametrize(
    "bad",
    [
        {"verdict": "strong"},
        {"verdict": "SUPPORTS"},
        {"schema_version": 2},
        {"surprise": True},
        {"fact_ids": "F-0001"},
        {"rationale": None},
    ],
)
def test_a_malformed_answer_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EntailmentOutput.model_validate({**VALID, **bad})


@pytest.mark.parametrize("missing", ["schema_version", "verdict", "fact_ids", "rationale"])
def test_every_field_is_required(missing: str) -> None:
    with pytest.raises(ValidationError):
        EntailmentOutput.model_validate({k: v for k, v in VALID.items() if k != missing})
