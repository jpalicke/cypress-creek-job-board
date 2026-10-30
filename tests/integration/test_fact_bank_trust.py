# ABOUTME: A bank built through the store gives the pipeline only verified facts to use.
# ABOUTME: It runs the real store, the real loader and the real prompt filter over a real file.
from pathlib import Path

import pytest

from cypress_creek.facts.errors import FactValidationError
from cypress_creek.facts.loader import load_bank
from cypress_creek.facts.models import Evidence, EvidenceType, Kind, Share
from cypress_creek.facts.store import BankStore, FactDraft
from cypress_creek.pipeline.prompt import prompt_facts
from cypress_creek.providers.base import Capabilities, CostPerMtok


def _draft(claim: str) -> FactDraft:
    return FactDraft(
        claim=claim,
        kind=Kind.PROJECT,
        evidence=Evidence(type=EvidenceType.SELF_ATTESTED, pointer="notes"),
    )


def _capabilities(*, local: bool) -> Capabilities:
    return Capabilities(
        context_tokens=8192,
        strict_schema=True,
        local=local,
        cost_per_mtok=CostPerMtok(input=0, output=0),
    )


@pytest.fixture
def store(tmp_path: Path) -> BankStore:
    store = BankStore(tmp_path / "bank.yaml")
    for number in range(1, 4):
        store.add(_draft(f"Claim number {number}."))
    return store


def test_only_a_fact_a_person_verified_reaches_a_model(store: BankStore) -> None:
    store.verify("F-0002")
    bank = load_bank(store.path)

    assert [f.id for f in prompt_facts(bank.facts, _capabilities(local=True))] == ["F-0002"]
    assert bank.unverified_ids() == ["F-0001", "F-0003"]


def test_a_hosted_backend_gets_only_verified_and_shareable_facts(store: BankStore) -> None:
    store.verify("F-0001")
    store.verify("F-0002")
    store.set_share("F-0002", Share.SHAREABLE)
    facts = load_bank(store.path).facts

    assert [f.id for f in prompt_facts(facts, _capabilities(local=False))] == ["F-0002"]


def test_editing_a_verified_fact_takes_it_out_of_the_prompt_again(store: BankStore) -> None:
    store.verify("F-0001")
    store.update("F-0001", _draft("A different claim."))

    assert prompt_facts(load_bank(store.path).facts, _capabilities(local=True)) == []


def test_a_bank_with_unverified_facts_still_fails_the_strict_load(store: BankStore) -> None:
    with pytest.raises(FactValidationError):
        load_bank(store.path, strict=True)
    for fact_id in ("F-0001", "F-0002", "F-0003"):
        store.verify(fact_id)

    assert len(load_bank(store.path, strict=True).facts) == 3
