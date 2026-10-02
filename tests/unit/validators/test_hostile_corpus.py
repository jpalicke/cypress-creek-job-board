# ABOUTME: Runs the hand written hostile outputs in fixtures/hostile_outputs through V1 to V14.
# ABOUTME: Every validator needs a corpus case it rejects, and a faithful output must still pass.
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from builders import requirement

from cypress_creek.facts.models import Bank, Fact
from cypress_creek.ingest.models import Importance, Requirement
from cypress_creek.validators import REGISTRY
from cypress_creek.validators.verdict import Verdict

CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "hostile_outputs"
BANK = Bank.model_validate_json((CORPUS / "bank.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Claim:
    text: str
    fact_ids: list[str]


def _facts(ids: list[str]) -> list[Fact]:
    return [fact for fact in BANK.facts if fact.id in ids]


def _requirement(data: dict[str, Any], snippet: str | None = None) -> Requirement:
    chosen = snippet if snippet is not None else data["snippet"]
    built = requirement(
        chosen,
        posting=data["posting"],
        importance=Importance(data.get("importance", "required")),
    )
    if "text_override" in data:
        built = built.model_copy(update={"text": data["text_override"]})
    return built


def _run_v1(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V1"].check(Requirement, data["data"])


def _run_v2(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V2"].check(data["posting"], _requirement(data))


def _run_v3(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V3"].check(data["posting"], _requirement(data))


def _run_v4(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V4"].check(data["cited_ids"], BANK)


def _run_v5(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V5"].check(data["cited_ids"], BANK)


def _run_v6(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V6"].check(data["cited_ids"], BANK, hosted=data["hosted"])


def _run_v7(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V7"].check(data["text"], _facts(data["cited_ids"]), BANK)


def _run_v8(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V8"].check(data["text"], _facts(data["cited_ids"]), data["requirement_text"])


def _run_v9(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V9"].check([Claim(c["text"], c["fact_ids"]) for c in data["claims"]])


def _run_v10(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V10"].check(data["text"], _facts(data["cited_ids"]), data["requirement_text"])


def _run_v11(data: dict[str, Any]) -> Verdict:
    stuffed = [
        requirement().model_copy(update={"term": term, "id": f"R-{n}"})
        for n, term in enumerate(data["terms"])
    ]
    return REGISTRY["V11"].check(stuffed)


def _run_v12(data: dict[str, Any]) -> Verdict:
    fact = _facts([data["fact_id"]])[0]
    return REGISTRY["V12"].check(fact, date.fromisoformat(data["today"]))


def _run_v13(data: dict[str, Any]) -> Verdict:
    found = [_requirement(data, snippet) for snippet in data["snippets"]]
    return REGISTRY["V13"].check(data["posting"], found)


def _run_v14(data: dict[str, Any]) -> Verdict:
    return REGISTRY["V14"].check(data["name"])


RUNNERS: dict[str, Callable[[dict[str, Any]], Verdict]] = {
    f"V{n}": runner
    for n, runner in enumerate(
        [
            _run_v1,
            _run_v2,
            _run_v3,
            _run_v4,
            _run_v5,
            _run_v6,
            _run_v7,
            _run_v8,
            _run_v9,
            _run_v10,
            _run_v11,
            _run_v12,
            _run_v13,
            _run_v14,
        ],
        start=1,
    )
}


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


CASE_FILES = sorted(CORPUS.glob("v[0-9][0-9]_*.json"))


@pytest.mark.parametrize("path", CASE_FILES, ids=[p.stem for p in CASE_FILES])
def test_hostile_output_is_rejected_by_its_validator(path: Path) -> None:
    case = _load(path)
    verdict = RUNNERS[case["validator"]](case["input"])
    assert verdict.validator == case["validator"]
    assert not verdict.passed, case["description"]
    assert verdict.reason


def test_every_validator_has_a_corpus_case() -> None:
    covered = {_load(path)["validator"] for path in CASE_FILES}
    assert covered == set(REGISTRY)
    assert set(RUNNERS) == set(REGISTRY)


def test_the_corpus_bank_loads_and_has_each_fact_shape_the_cases_need() -> None:
    assert [fact.id for fact in BANK.verified_facts()] == ["F-0001", "F-0002", "F-0004"]


def test_a_faithful_rationale_passes_the_grounding_checks() -> None:
    data = _load(CORPUS / "grounded_rationale.json")["input"]
    for runner in (_run_v7, _run_v8, _run_v9, _run_v10):
        verdict = runner(data)
        assert verdict.passed, (verdict.validator, verdict.reason, verdict.offending)
