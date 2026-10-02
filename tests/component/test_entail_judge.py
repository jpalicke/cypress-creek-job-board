# ABOUTME: Tests how entailment output is judged: clamped to the ceiling, citations and rationale
# ABOUTME: checked by the validators. Hostile outputs run against a real fact bank file.
from pathlib import Path

import pytest

from cypress_creek.facts import load_bank
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind
from cypress_creek.pipeline.entail import RATIONALE_WITHHELD, EntailedMatch, Entailment, judge
from cypress_creek.pipeline.schemas import EntailmentOutput, EntailmentVerdict
from cypress_creek.providers.base import Capabilities, CostPerMtok
from cypress_creek.scoring.support import Support

FREE = CostPerMtok(input=0, output=0)
LOCAL = Capabilities(context_tokens=8192, strict_schema=True, local=True, cost_per_mtok=FREE)
HOSTED = Capabilities(context_tokens=8192, strict_schema=True, local=False, cost_per_mtok=FREE)
STRONG, PARTIAL, NONE = Support.STRONG, Support.PARTIAL, Support.NONE

BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 3 years.
    kind: project
    employer: Fictional Mills
    start: 2020-01-01
    end: 2023-01-01
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
  - id: F-0002
    claim: Operated a fictional PostgreSQL cluster.
    kind: project
    employer: Imaginary Docks
    tags: [{name: postgresql, level: working}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/b"}
    share: shareable
  - id: F-0003
    claim: Claimed Go work with no verification.
    kind: project
    tags: [{name: go, level: expert}]
    evidence: {type: self_attested, pointer: notes}
    share: shareable
  - id: F-0004
    claim: Private fictional Rust work.
    kind: project
    tags: [{name: rust, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: self_attested, pointer: notes}
    share: local_only
"""


@pytest.fixture
def bank(tmp_path: Path) -> Bank:
    path = tmp_path / "bank.yaml"
    path.write_text(BANK, encoding="utf8")
    return load_bank(path)


REQUIREMENT = Requirement(
    id="R-1",
    text="Needs Python.",
    span=(0, 13),
    kind=RequirementKind.SKILL,
    term="python",
    importance=Importance.REQUIRED,
)
CANDIDATES = ["F-0001", "F-0002"]


def _output(
    verdict: EntailmentVerdict = EntailmentVerdict.SUPPORTS,
    fact_ids: list[str] | None = None,
    rationale: str = "Fact F-0001 shows Python work.",
) -> EntailmentOutput:
    return EntailmentOutput(
        schema_version=1,
        verdict=verdict,
        fact_ids=["F-0001"] if fact_ids is None else fact_ids,
        rationale=rationale,
    )


def _judge(
    bank: Bank,
    output: EntailmentOutput,
    ceiling: Support = STRONG,
    capabilities: Capabilities = LOCAL,
    candidates: list[str] | None = None,
) -> EntailedMatch:
    return judge(
        output,
        REQUIREMENT,
        CANDIDATES if candidates is None else candidates,
        ceiling,
        bank,
        capabilities,
    )


def test_a_model_attempt_to_raise_support_is_clamped_and_counted(bank: Bank) -> None:
    result = _judge(bank, _output(EntailmentVerdict.SUPPORTS), ceiling=PARTIAL)
    assert result.match.support is PARTIAL
    assert result.match.ceiling is PARTIAL
    assert result.raise_attempted
    assert result.entailment is Entailment.CONFIRMED


def test_a_verdict_above_a_ceiling_of_none_stays_none(bank: Bank) -> None:
    result = _judge(bank, _output(EntailmentVerdict.PARTIAL), ceiling=NONE)
    assert result.match.support is NONE
    assert result.raise_attempted


def test_does_not_support_lowers_a_strong_ceiling_to_none(bank: Bank) -> None:
    result = _judge(bank, _output(EntailmentVerdict.DOES_NOT_SUPPORT, fact_ids=[]), ceiling=STRONG)
    assert result.match.support is NONE
    assert result.entailment is Entailment.DOWNGRADED
    assert not result.raise_attempted


def test_partial_lowers_a_strong_ceiling_one_step(bank: Bank) -> None:
    result = _judge(bank, _output(EntailmentVerdict.PARTIAL), ceiling=STRONG)
    assert result.match.support is PARTIAL
    assert result.entailment is Entailment.DOWNGRADED


def test_agreement_confirms_the_ceiling(bank: Bank) -> None:
    result = _judge(bank, _output(EntailmentVerdict.SUPPORTS), ceiling=STRONG)
    assert result.match.support is STRONG
    assert result.entailment is Entailment.CONFIRMED
    assert not result.raise_attempted
    assert result.fact_ids == ["F-0001"]
    assert result.rationale == "Fact F-0001 shows Python work."


@pytest.mark.parametrize(
    "cited",
    [["F-9999"], ["F-0003"], []],
    ids=["not_in_bank", "unverified", "no_citation"],
)
def test_a_positive_verdict_without_a_valid_citation_is_does_not_support(
    bank: Bank, cited: list[str]
) -> None:
    result = _judge(bank, _output(fact_ids=cited), candidates=["F-0001", "F-0003"])
    assert result.match.support is NONE
    assert result.entailment is Entailment.DOWNGRADED
    assert result.fact_ids == []
    assert result.rationale == RATIONALE_WITHHELD


def test_a_verified_fact_that_was_not_a_candidate_is_not_a_valid_citation(bank: Bank) -> None:
    result = _judge(bank, _output(fact_ids=["F-0002"]), candidates=["F-0001"])
    assert result.match.support is NONE
    assert result.fact_ids == []


def test_a_local_only_fact_cannot_be_cited_from_a_hosted_backend(bank: Bank) -> None:
    only = ["F-0004"]
    hosted = _judge(bank, _output(fact_ids=only), capabilities=HOSTED, candidates=only)
    local = _judge(bank, _output(fact_ids=only), capabilities=LOCAL, candidates=only)
    assert hosted.match.support is NONE
    assert local.match.support is STRONG


def test_an_invalid_id_is_dropped_and_a_valid_one_keeps_the_verdict(bank: Bank) -> None:
    result = _judge(bank, _output(fact_ids=["F-9999", "F-0001", "F-0001"]))
    assert result.fact_ids == ["F-0001"]
    assert result.match.support is STRONG


def test_a_rationale_with_a_number_that_is_in_no_cited_fact_is_withheld(bank: Bank) -> None:
    result = _judge(bank, _output(rationale="Fact F-0001 shows 9 years of Python."))
    assert result.rationale == RATIONALE_WITHHELD
    assert result.match.support is STRONG


def test_a_rationale_naming_the_employer_of_an_uncited_fact_is_withheld(bank: Bank) -> None:
    result = _judge(bank, _output(rationale="Fact F-0001 shows Python work at Imaginary Docks."))
    assert result.rationale == RATIONALE_WITHHELD


def test_a_rationale_inventing_an_employer_is_withheld(bank: Bank) -> None:
    result = _judge(bank, _output(rationale="Fact F-0001 shows Python work at Globex Corporation."))
    assert result.rationale == RATIONALE_WITHHELD
    assert result.match.support is STRONG


def test_a_withheld_rationale_never_changes_the_support(bank: Bank) -> None:
    clean = _judge(bank, _output())
    hostile = _judge(bank, _output(rationale="Led 40 engineers at Globex Corporation."))
    assert clean.match == hostile.match


def test_a_negative_verdict_may_cite_nothing_and_keeps_a_grounded_rationale(bank: Bank) -> None:
    output = _output(
        EntailmentVerdict.DOES_NOT_SUPPORT, fact_ids=[], rationale="The facts do not show it."
    )
    assert _judge(bank, output).rationale == "The facts do not show it."


def test_a_blank_rationale_is_nothing_to_show(bank: Bank) -> None:
    assert _judge(bank, _output(rationale="  ")).rationale is None
