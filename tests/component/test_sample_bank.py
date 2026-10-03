# ABOUTME: Tests that the shipped sample fact bank loads strictly and has its planted properties.
# ABOUTME: The sample bank is fictional, so evals and docs can use it without private data.
import itertools
from datetime import date
from pathlib import Path

import pytest

from cypress_creek.facts import load_bank
from cypress_creek.facts.errors import FactValidationError
from cypress_creek.facts.models import Bank, EvidenceType, Kind, Level, Share
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind
from cypress_creek.pipeline.retrieve import retrieve
from cypress_creek.providers.base import Capabilities, CostPerMtok
from cypress_creek.scoring.aliases import load_aliases

SAMPLE_BANK_DIR = Path(__file__).parent.parent.parent / "evals" / "bank"
SAMPLE_BANK = SAMPLE_BANK_DIR / "sample_bank.yaml"
UNVERIFIED_BANK = SAMPLE_BANK_DIR / "sample_bank_unverified.yaml"
PLANTED_GAPS = SAMPLE_BANK_DIR / "PLANTED_GAPS.md"
TODAY = date(2024, 6, 1)
CAPABILITIES = Capabilities(
    context_tokens=8192,
    strict_schema=True,
    local=True,
    cost_per_mtok=CostPerMtok(input=0, output=0),
)


def test_the_sample_bank_loads_in_strict_mode() -> None:
    bank = load_bank(SAMPLE_BANK, strict=True)
    assert bank.facts
    assert len({fact.id for fact in bank.facts}) == len(bank.facts)


def _bank() -> Bank:
    return load_bank(SAMPLE_BANK, strict=True)


def test_tags_exist_at_every_level() -> None:
    levels = {tag.level for fact in _bank().facts for tag in fact.tags}
    assert levels == set(Level)


def test_facts_exist_with_every_evidence_type() -> None:
    assert {fact.evidence.type for fact in _bank().facts} == set(EvidenceType)


def test_facts_exist_for_education_and_certification() -> None:
    kinds = {fact.kind for fact in _bank().facts}
    assert {Kind.EDUCATION, Kind.CERTIFICATION} <= kinds


def test_at_least_two_facts_are_local_only() -> None:
    local = [fact for fact in _bank().facts if fact.share is Share.LOCAL_ONLY]
    assert len(local) >= 2


def test_a_claim_is_near_the_character_cap() -> None:
    assert max(len(fact.claim) for fact in _bank().facts) >= 280


def test_employers_have_overlapping_and_separate_periods() -> None:
    periods = [
        (fact.start, fact.end)
        for fact in _bank().facts
        if fact.kind is Kind.EMPLOYMENT and fact.start and fact.end
    ]
    pairs = list(itertools.combinations(periods, 2))
    overlapping = [pair for pair in pairs if pair[0][0] <= pair[1][1] and pair[1][0] <= pair[0][1]]
    separate = [pair for pair in pairs if pair not in overlapping]
    assert overlapping
    assert separate


def test_the_sample_bank_has_at_least_twenty_five_facts() -> None:
    assert len(_bank().facts) >= 25


def test_the_verified_sample_bank_has_no_unverified_fact() -> None:
    assert _bank().unverified_ids() == []


def test_the_unverified_bank_loads_with_one_unverified_fact_and_fails_strict_mode() -> None:
    bank = load_bank(UNVERIFIED_BANK)
    assert bank.unverified_ids() == ["F-0026"]
    with pytest.raises(FactValidationError, match="verified_on"):
        load_bank(UNVERIFIED_BANK, strict=True)


def test_fact_ids_are_unique_across_both_sample_banks() -> None:
    ids = [fact.id for fact in _bank().facts + load_bank(UNVERIFIED_BANK).facts]
    assert len(ids) == len(set(ids))


def _planted_gap_rows() -> list[dict[str, str]]:
    """The rows of the table in PLANTED_GAPS.md, keyed by its header names."""
    lines = [
        line.strip()
        for line in PLANTED_GAPS.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("|")
    ]
    header, _divider, *body = [
        [cell.strip() for cell in line.strip("|").split("|")] for line in lines
    ]
    return [dict(zip(header, row, strict=True)) for row in body]


def test_planted_gaps_lists_every_kind_of_support() -> None:
    assert {row["Support"] for row in _planted_gap_rows()} == {"strong", "partial", "none"}


@pytest.mark.parametrize("row", _planted_gap_rows(), ids=lambda row: f"{row['Kind']}-{row['Term']}")
def test_the_support_gate_gives_each_planted_row_its_documented_answer(
    row: dict[str, str],
) -> None:
    """The document and the bank cannot drift: each row is checked by the real retrieval."""
    requirement = Requirement(
        id="R-1",
        text=row["Term"],
        span=(0, len(row["Term"])),
        kind=RequirementKind(row["Kind"]),
        term=row["Term"],
        years=int(row["Years"]) if row["Years"] else None,
        issuer=row["Issuer"] or None,
        importance=Importance.REQUIRED,
    )
    candidates = retrieve([requirement], _bank(), CAPABILITIES, TODAY, load_aliases())[0]
    assert (candidates.support.value, candidates.gate.value) == (row["Support"], row["Gate"])


def test_a_planted_gap_the_unverified_bank_would_fill_stays_a_gap() -> None:
    """The verified bank gives no Go support even though the unverified file claims it."""
    go = Requirement(
        id="R-1",
        text="Go",
        span=(0, 2),
        kind=RequirementKind.SKILL,
        term="go",
        importance=Importance.REQUIRED,
    )
    both = Bank(facts=_bank().facts + load_bank(UNVERIFIED_BANK).facts)
    candidates = retrieve([go], both, CAPABILITIES, TODAY, load_aliases())[0]
    assert candidates.is_gap
