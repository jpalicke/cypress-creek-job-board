# ABOUTME: Tests that the shipped sample fact bank loads strictly and has its planted properties.
# ABOUTME: The sample bank is fictional, so evals and docs can use it without private data.
from pathlib import Path

from cypress_creek.facts import load_bank

SAMPLE_BANK = Path(__file__).parent.parent.parent / "evals" / "bank" / "sample_bank.yaml"


def test_the_sample_bank_loads_in_strict_mode() -> None:
    bank = load_bank(SAMPLE_BANK, strict=True)
    assert bank.facts
    assert len({fact.id for fact in bank.facts}) == len(bank.facts)
