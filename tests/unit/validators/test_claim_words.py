# ABOUTME: Tests the quantity words that V8 checks and the negation list the draft check uses.
# ABOUTME: The default V10 stays unchanged, because rationales may say "the facts do not show".
import pytest
from builders import fact

from cypress_creek.facts.models import Fact, Level, Tag
from cypress_creek.validators.claim_words import (
    negation_words,
    quantity_words,
)
from cypress_creek.validators.claims import check_novel_terms
from cypress_creek.validators.consistency import check_numbers

LED = fact(
    1,
    claim="Led a team of 8 engineers moving a billing system to Python.",
    employer="Initech",
    role="Tech Lead",
    tags=[Tag(name="python", level=Level.EXPERT)],
)


def _fact(claim: str, role: str = "Engineer", tags: list[Tag] | None = None) -> Fact:
    return fact(2, claim=claim, employer="Initech", role=role, tags=tags)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("for a decade", {"decade"}),
        ("for two decades and a dozen releases", {"decade", "dozen"}),
        ("a couple of teams, half the staff", {"couple", "half"}),
        ("doubling, tripled and quadrupled", {"double", "triple", "quadruple"}),
        (
            "hundreds of users, thousands of requests, millions of rows",
            {"hundreds", "thousands", "millions"},
        ),
        ("numerous releases", {"numerous"}),
        ("double-checked the config", set()),
        ("a halfway house and a halfpipe", set()),
        ("the doubleclick tag", set()),
        ("decades-old code", set()),
        ("", set()),
    ],
)
def test_quantity_words(text: str, expected: set[str]) -> None:
    assert quantity_words(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Never led a team", {"negation"}),
        ("did not own it", {"negation"}),
        ("didn't ship", {"negation"}),
        ("shipped without tests", {"negation"}),
        ("no outages, none reported, nor any delays", {"negation"}),
        ("failed to launch", {"negation"}),
        ("Led a team of 8 engineers", set()),
        ("a note about knots", set()),
        ("annotated the notebook", set()),
    ],
)
def test_negation_words(text: str, expected: set[str]) -> None:
    assert negation_words(text) == expected


def test_v8_flags_a_quantity_word_that_no_cited_fact_uses() -> None:
    verdict = check_numbers("Led 8 engineers moving billing to Python for a decade.", [LED], "")
    assert not verdict.passed
    assert verdict.validator == "V8"
    assert verdict.offending == "decade"


def test_v8_allows_a_quantity_word_the_cited_fact_uses() -> None:
    cited = _fact("Maintained the ledger for a decade.")
    assert check_numbers("Maintained the ledger for a decade.", [cited], "").passed


def test_v8_allows_a_quantity_word_the_requirement_uses_when_it_is_given() -> None:
    assert check_numbers("Over a decade of Python.", [LED], "A decade of Python required").passed


def test_v8_ignores_compounds_with_hyphens() -> None:
    assert check_numbers("Double-checked the 8 engineers' work.", [LED], "").passed


def test_v10_is_unchanged_by_default() -> None:
    text = "Doubled revenue, never missed a deadline, as senior staff"
    assert check_novel_terms(text, [LED], "").passed
