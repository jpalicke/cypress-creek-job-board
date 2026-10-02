# ABOUTME: Tests the bank hash and the derived run id, which must change with every run input.
# ABOUTME: The same posting, bank, backend and model always give the same id.
import re

from cypress_creek.facts.hashing import bank_hash
from cypress_creek.facts.models import Bank, Evidence, EvidenceType, Fact, Kind, Share
from cypress_creek.pipeline.run import run_id

TEXT_HASH = "a" * 64


def _fact(fact_id: str, claim: str) -> Fact:
    return Fact(
        id=fact_id,
        claim=claim,
        kind=Kind.PROJECT,
        tags=[],
        evidence=Evidence(type=EvidenceType.REPO, pointer="https://example.invalid/a"),
        share=Share.SHAREABLE,
    )


def test_the_bank_hash_is_a_sha256_of_the_facts() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", bank_hash(Bank(facts=[_fact("F-0001", "Ran a thing.")])))


def test_the_bank_hash_ignores_the_order_of_the_facts() -> None:
    one, two = _fact("F-0001", "Ran a thing."), _fact("F-0002", "Ran another thing.")
    assert bank_hash(Bank(facts=[one, two])) == bank_hash(Bank(facts=[two, one]))


def test_the_bank_hash_changes_when_a_claim_changes() -> None:
    before = Bank(facts=[_fact("F-0001", "Ran a thing.")])
    after = Bank(facts=[_fact("F-0001", "Ran a bigger thing.")])
    assert bank_hash(before) != bank_hash(after)


def test_the_run_id_has_a_prefix_and_sixteen_hex_characters() -> None:
    assert re.fullmatch(r"run-[0-9a-f]{16}", run_id(TEXT_HASH, "b" * 64, "ollama", "m"))


def test_the_same_inputs_give_the_same_run_id() -> None:
    first = run_id(TEXT_HASH, "b" * 64, "ollama", "m")
    assert first == run_id(TEXT_HASH, "b" * 64, "ollama", "m")


def test_every_input_changes_the_run_id() -> None:
    base = run_id(TEXT_HASH, "b" * 64, "ollama", "m")
    assert run_id("c" * 64, "b" * 64, "ollama", "m") != base
    assert run_id(TEXT_HASH, "c" * 64, "ollama", "m") != base
    assert run_id(TEXT_HASH, "b" * 64, "anthropic", "m") != base
    assert run_id(TEXT_HASH, "b" * 64, "ollama", "other") != base


def test_fields_cannot_run_together_into_the_same_id() -> None:
    assert run_id(TEXT_HASH, "b" * 64, "ab", "c") != run_id(TEXT_HASH, "b" * 64, "a", "bc")
