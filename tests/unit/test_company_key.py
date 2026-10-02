# ABOUTME: Tests company_key, the one normalizer every company comparison goes through.
# ABOUTME: Covers suffix, spacing and homoglyph variants, hostile names and Hypothesis properties.
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.storage.company_key import LEGAL_SUFFIXES, CompanyNameError, company_key

# Latin "Acme" with Cyrillic a (U+0430), c (U+0441) and e (U+0435) in place of the Latin letters.
CYRILLIC_ACME = "асmе"


@pytest.mark.parametrize(
    "variant",
    [
        "Acme, Inc.",
        "ACME Incorporated",
        "Acme Inc",
        "acme",
        "  Acme   Inc.  ",
        "A.C.M.E.",
        "Ac me",
        "Acme Inc Inc",
        "Acme (Inc)",
        "Acme, L.L.C.",
        "Acme-Inc",
        "ACME​ Inc",
        "A‍cme",
        "Ac​me",
        "Ａｃｍｅ",
        "Àcmé",
        CYRILLIC_ACME,
        CYRILLIC_ACME.upper() + " Inc.",
        "Αcme",
        "Acme Сorp",
    ],
)
def test_variants_of_one_company_produce_one_key(variant: str) -> None:
    assert company_key(variant) == "acme"


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Rolls-Royce", "rollsroyce"),
        ("O'Reilly Media", "oreillymedia"),
        ("AT&T", "att"),
        ("3M Company", "3mcompany"),
        ("Nestlé S.A.", "nestlesa"),
        # Homoglyph letters fold even inside a genuinely Cyrillic name. Keys are only compared.
        ("Яндекс", "яндekc"),
    ],
)
def test_keys_for_real_looking_names(name: str, key: str) -> None:
    assert company_key(name) == key


@pytest.mark.parametrize("suffix", sorted(LEGAL_SUFFIXES))
def test_each_legal_suffix_is_stripped(suffix: str) -> None:
    assert company_key(f"Acme {suffix}") == "acme"
    assert company_key(f"Acme, {suffix.upper()}.") == "acme"


def test_a_suffix_in_the_middle_of_a_name_is_kept() -> None:
    assert company_key("Inc Acme") == "incacme"


def test_a_name_that_is_only_a_suffix_keeps_it() -> None:
    assert company_key("Inc.") == "inc"


def test_different_companies_have_different_keys() -> None:
    assert company_key("Acme") != company_key("Acne")
    assert company_key("Acme Robotics") != company_key("Acme")


@pytest.mark.parametrize("name", ["", "   ", "...", "-- ,, !!", "​‍", "()", "\U0001f600"])
def test_empty_or_punctuation_only_names_raise(name: str) -> None:
    with pytest.raises(CompanyNameError):
        company_key(name)


def test_absurdly_long_names_are_refused() -> None:
    with pytest.raises(CompanyNameError, match="too long"):
        company_key("a" * 1001)


@given(st.text(max_size=200))
def test_key_is_idempotent_and_only_raises_its_typed_error(name: str) -> None:
    try:
        key = company_key(name)
    except CompanyNameError:
        return
    assert key
    assert company_key(key) == key
    assert key.isalnum()
