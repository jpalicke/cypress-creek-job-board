# ABOUTME: Tests that the shipped sample fact bank loads strictly and has its planted properties.
# ABOUTME: The sample bank is fictional, so evals and docs can use it without private data.
import itertools
from pathlib import Path

from cypress_creek.facts import load_bank
from cypress_creek.facts.models import Bank, EvidenceType, Kind, Level, Share

SAMPLE_BANK = Path(__file__).parent.parent.parent / "evals" / "bank" / "sample_bank.yaml"


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
