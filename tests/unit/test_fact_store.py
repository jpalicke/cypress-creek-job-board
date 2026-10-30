# ABOUTME: Unit tests for the fact bank store: add, edit, share, verify and delete on a real file.
# ABOUTME: Verification is only ever set by verify(); editing what a fact says takes it away again.
import os
import stat
from datetime import date
from pathlib import Path

import pytest

from cypress_creek.facts.errors import BankLoadError, FactValidationError
from cypress_creek.facts.loader import load_bank
from cypress_creek.facts.models import Evidence, EvidenceType, Kind, Level, Share, Tag
from cypress_creek.facts.store import BankStore, FactDraft, FactNotFound

TODAY = date(2026, 6, 1)


def draft(**changes: object) -> FactDraft:
    values: dict[str, object] = {
        "claim": "Built a reporting service in Python.",
        "kind": Kind.PROJECT,
        "tags": [Tag(name="python", level=Level.WORKING)],
        "evidence": Evidence(type=EvidenceType.SELF_ATTESTED, pointer="my notes"),
    }
    values.update(changes)
    return FactDraft.model_validate(values)


@pytest.fixture
def store(tmp_path: Path) -> BankStore:
    return BankStore(tmp_path / "private" / "bank.yaml")


def test_a_missing_bank_file_is_an_empty_bank_and_nothing_is_created_by_reading(
    store: BankStore,
) -> None:
    assert store.facts() == []
    assert not store.path.exists()


def test_a_new_fact_is_unverified_and_local_only_with_a_server_assigned_id(
    store: BankStore,
) -> None:
    fact = store.add(draft())

    assert fact.id == "F-0001"
    assert fact.verified_on is None and not fact.is_verified
    assert fact.share is Share.LOCAL_ONLY
    assert [f.id for f in store.facts()] == ["F-0001"]


def test_the_file_is_written_private_and_loads_with_the_normal_loader(store: BankStore) -> None:
    store.add(draft())
    store.add(draft(claim="Ran the nightly batch."))

    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    assert [f.claim for f in load_bank(store.path).facts] == [
        "Built a reporting service in Python.",
        "Ran the nightly batch.",
    ]


def test_an_id_is_never_reused_after_a_delete(store: BankStore) -> None:
    first = store.add(draft())
    store.delete(first.id)

    assert store.add(draft()).id == "F-0002"


def test_verify_sets_the_date_and_only_for_that_fact(store: BankStore) -> None:
    one, two = store.add(draft()), store.add(draft(claim="Another claim."))

    verified = store.verify(one.id, today=TODAY)

    assert verified.verified_on == TODAY
    assert store.get(two.id).verified_on is None


def test_editing_what_a_fact_says_returns_it_to_unverified(store: BankStore) -> None:
    fact = store.add(draft())
    store.verify(fact.id, today=TODAY)

    edited = store.update(fact.id, draft(claim="Built a different service."), today=TODAY)

    assert edited.verified_on is None


@pytest.mark.parametrize(
    "change",
    [
        {"employer": "Gravy Boat Labs"},
        {"role": "Developer"},
        {"start": date(2020, 1, 1)},
        {"tags": [Tag(name="sql", level=Level.EXPERT)]},
        {"kind": Kind.EMPLOYMENT},
        {"evidence": Evidence(type=EvidenceType.REPO, pointer="https://example.com/r")},
    ],
)
def test_changing_any_substantive_field_also_unverifies(
    store: BankStore, change: dict[str, object]
) -> None:
    fact = store.add(draft())
    store.verify(fact.id, today=TODAY)

    assert store.update(fact.id, draft(**change), today=TODAY).verified_on is None


def test_saving_an_unchanged_fact_keeps_it_verified(store: BankStore) -> None:
    fact = store.add(draft())
    store.verify(fact.id, today=TODAY)

    assert store.update(fact.id, draft(), today=TODAY).verified_on == TODAY


def test_changing_the_share_state_is_separate_and_keeps_verification(store: BankStore) -> None:
    fact = store.add(draft())
    store.verify(fact.id, today=TODAY)

    shared = store.set_share(fact.id, Share.SHAREABLE)

    assert shared.share is Share.SHAREABLE and shared.verified_on == TODAY


def test_unverify_clears_the_date(store: BankStore) -> None:
    fact = store.add(draft())
    store.verify(fact.id, today=TODAY)

    assert store.unverify(fact.id).verified_on is None


def test_an_invalid_fact_names_the_field_and_saves_nothing(store: BankStore) -> None:
    with pytest.raises(FactValidationError) as caught:
        store.add(draft(start=date(2030, 1, 1)), today=TODAY)

    assert caught.value.field == "start"
    assert store.facts() == []


def test_an_end_before_the_start_is_refused(store: BankStore) -> None:
    with pytest.raises(FactValidationError):
        store.add(draft(start=date(2020, 5, 1), end=date(2019, 1, 1)), today=TODAY)


def test_an_unknown_fact_raises_not_found(store: BankStore) -> None:
    store.add(draft())

    for action in (
        lambda: store.get("F-0099"),
        lambda: store.update("F-0099", draft()),
        lambda: store.verify("F-0099"),
        lambda: store.delete("F-0099"),
    ):
        with pytest.raises(FactNotFound):
            action()


def test_a_corrupt_bank_file_is_never_overwritten(store: BankStore) -> None:
    store.path.parent.mkdir(parents=True)
    store.path.write_text("facts: [this is not a fact]\n", encoding="utf-8")

    with pytest.raises(BankLoadError):
        store.add(draft())

    assert store.path.read_text(encoding="utf-8") == "facts: [this is not a fact]\n"


def test_hostile_text_is_stored_and_read_back_unchanged(store: BankStore) -> None:
    hostile = "<script>alert(1)</script> & <img src=x onerror=alert(2)>"

    fact = store.add(draft(claim=hostile))

    assert load_bank(store.path).facts[0].claim == hostile
    assert fact.claim == hostile
