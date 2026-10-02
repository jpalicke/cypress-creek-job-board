# ABOUTME: Tests fact bank parsing rules, each failure raises a typed error naming fact and field.
# ABOUTME: Covers strict and normal verification, id rules, enums, date sanity, the verified view.
from copy import deepcopy
from datetime import date
from typing import Any

import pytest

from cypress_creek.facts.errors import FactValidationError
from cypress_creek.facts.loader import parse_bank

TODAY = date(2026, 10, 1)

FACT: dict[str, Any] = {
    "id": "F-0001",
    "claim": "Built a nightly report generator for a fictional logistics team.",
    "kind": "project",
    "employer": "Example Freight Co",
    "role": "Engineer",
    "start": date(2022, 1, 1),
    "end": date(2023, 1, 1),
    "tags": [{"name": "python", "level": "expert"}],
    "verified_on": date(2024, 5, 1),
    "evidence": {"type": "repo", "pointer": "https://example.invalid/repo"},
    "share": "shareable",
}


def bank_with(**changes: Any) -> dict[str, Any]:
    fact = deepcopy(FACT)
    for key, value in changes.items():
        if value is None:
            fact.pop(key, None)
        else:
            fact[key] = value
    return {"facts": [fact]}


def error_for(data: dict[str, Any], **kwargs: Any) -> FactValidationError:
    with pytest.raises(FactValidationError) as caught:
        parse_bank(data, today=TODAY, **kwargs)
    return caught.value


def test_fact_missing_verified_on_is_rejected_in_strict_mode() -> None:
    error = error_for(bank_with(verified_on=None), strict=True)
    assert (error.fact_id, error.field) == ("F-0001", "verified_on")


def test_fact_missing_verified_on_loads_as_unverified_in_normal_mode() -> None:
    bank = parse_bank(bank_with(verified_on=None), today=TODAY)
    assert bank.unverified_ids() == ["F-0001"]
    assert bank.verified_facts() == []


def test_malformed_verified_on_is_rejected_in_both_modes() -> None:
    for strict in (True, False):
        error = error_for(bank_with(verified_on="2024-13-45"), strict=strict)
        assert error.field == "verified_on"


def test_valid_bank_loads_and_exposes_the_verified_view() -> None:
    bank = parse_bank(bank_with(), today=TODAY, strict=True)
    assert [fact.id for fact in bank.verified_facts()] == ["F-0001"]
    assert bank.unverified_ids() == []


@pytest.mark.parametrize("bad_id", ["F-1", "f-0001", "F-00001", "X-0001", ""])
def test_bad_id_pattern_is_rejected(bad_id: str) -> None:
    assert error_for(bank_with(id=bad_id)).field == "id"


def test_duplicate_ids_are_rejected() -> None:
    data = bank_with()
    data["facts"].append(deepcopy(data["facts"][0]))
    error = error_for(data)
    assert (error.fact_id, error.field) == ("F-0001", "id")
    assert "duplicate" in error.reason


def test_claim_over_300_characters_is_rejected() -> None:
    assert error_for(bank_with(claim="x" * 301)).field == "claim"


def test_empty_claim_is_rejected() -> None:
    assert error_for(bank_with(claim="  ")).field == "claim"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "hobby"),
        ("share", "everyone"),
        ("evidence", {"type": "vibes", "pointer": "x"}),
        ("tags", [{"name": "python", "level": "guru"}]),
    ],
)
def test_unknown_enum_values_are_rejected(field: str, value: Any) -> None:
    assert error_for(bank_with(**{field: value})).field == field


def test_start_after_end_is_rejected() -> None:
    error = error_for(bank_with(start=date(2024, 1, 1), end=date(2023, 1, 1)))
    assert error.field == "start"


@pytest.mark.parametrize("field", ["start", "end", "verified_on"])
def test_future_dates_are_rejected(field: str) -> None:
    changes: dict[str, Any] = {field: date(2027, 1, 1)}
    if field == "start":
        changes["end"] = None
    assert error_for(bank_with(**changes)).field == field


def test_unknown_field_is_rejected() -> None:
    assert error_for(bank_with(confidence="high")).field == "confidence"


def test_share_defaults_to_local_only() -> None:
    bank = parse_bank(bank_with(share=None), today=TODAY)
    assert bank.facts[0].share == "local_only"


def test_missing_required_field_names_the_field() -> None:
    assert error_for(bank_with(claim=None)).field == "claim"


def test_fact_without_an_id_is_reported_with_its_position() -> None:
    error = error_for(bank_with(id=None))
    assert error.field == "id"
    assert error.fact_id == "facts[0]"
