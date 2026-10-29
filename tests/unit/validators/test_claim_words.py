# ABOUTME: Tests claim words: quantity words in V8, and impact, seniority and negation in V10.
# ABOUTME: Includes legitimate paraphrases that must pass, because a flag costs a human review.
import pytest
from builders import fact

from cypress_creek.facts.models import Fact, Level, Tag
from cypress_creek.validators.claim_words import (
    impact_words,
    negation_words,
    quantity_words,
    seniority_words,
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
        ("doubling revenue", {"double", "revenue"}),
        ("reduced and cut costs, shortened builds", {"reduce", "cost"}),
        ("increased sales and boosted profit", {"increase", "revenue"}),
        ("improved and optimized throughput", {"improve"}),
        ("saved money, big savings", {"save"}),
        ("won an award", {"award"}),
        ("made it faster", {"speed"}),
        ("a costume party", set()),
        ("Led the migration", set()),
        ("moving a billing system", set()),
    ],
)
def test_impact_words(text: str, expected: set[str]) -> None:
    assert impact_words(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("senior staff engineers", {"senior", "staff"}),
        ("a principal architect and chief of staff", {"principal", "architect", "chief", "staff"}),
        (
            "single-handedly built a world-class, large-scale system",
            {"single-handedly", "world-class", "large-scale"},
        ),
        ("the sole owner", {"sole"}),
        ("Led a team of 8 engineers", set()),
        ("seniority", set()),
        ("staffed the desk", set()),
    ],
)
def test_seniority_words(text: str, expected: set[str]) -> None:
    assert seniority_words(text) == expected


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


@pytest.mark.parametrize(
    "sentence,word",
    [
        (
            "Led a team of 8 engineers moving a billing system to Python, doubling revenue.",
            "double",
        ),
        ("Led a team of 8 engineers, cutting costs.", "cost"),
        ("Led a team of 8 senior staff engineers moving a billing system to Python.", "senior"),
        ("Led a team of 8 engineers as the sole owner.", "sole"),
        ("Never led a team of 8 engineers moving a billing system to Python.", "negation"),
        ("Led a team of 8 engineers without delays.", "negation"),
        ("Won an award leading a team of 8 engineers.", "award"),
    ],
)
def test_v10_claim_words_flag_what_no_cited_fact_says(sentence: str, word: str) -> None:
    verdict = check_novel_terms(sentence, [LED], "", claim_words=True)
    assert not verdict.passed
    assert verdict.validator == "V10"
    assert verdict.offending is not None
    assert word in verdict.offending or verdict.offending == word


def test_v10_allows_a_claim_word_a_cited_fact_uses_in_any_inflection() -> None:
    cited = _fact("Doubled throughput of the billing service.")
    sentence = "Doubling the throughput of the billing service."
    assert check_novel_terms(sentence, [cited], "", claim_words=True).passed


def test_v10_counts_the_role_and_tag_level_as_fact_text() -> None:
    cited = _fact(
        "Ran the data service.", role="Senior Engineer", tags=[Tag(name="sql", level=Level.EXPERT)]
    )
    assert check_novel_terms(
        "Senior engineer who ran the data service.", [cited], "", claim_words=True
    ).passed
    assert check_novel_terms("Expert in the data service.", [cited], "", claim_words=True).passed


def test_v10_flags_a_dropped_negation() -> None:
    cited = _fact("Never missed a release date in 3 years.")
    verdict = check_novel_terms("Missed a release date in 3 years.", [cited], "", claim_words=True)
    assert not verdict.passed
    assert verdict.offending == "negation dropped"


def test_v10_allows_a_negation_the_cited_fact_has() -> None:
    cited = _fact("Never missed a release date in 3 years.")
    assert check_novel_terms(
        "Never missed a release date in 3 years.", [cited], "", claim_words=True
    ).passed


# What a flag costs is a human review, so ordinary paraphrases of a fact must not trip it.
PARAPHRASES = [
    (
        "Led a team of 8 engineers moving a billing system to Python.",
        "Led 8 engineers in moving a billing system to Python.",
    ),
    (
        "Led a team of 8 engineers moving a billing system to Python.",
        "Led an 8 person engineering team migrating the billing system to Python.",
    ),
    ("Built a reporting dashboard for customers.", "Built customer reporting dashboards."),
    (
        "Ran PostgreSQL in production for payments.",
        "Operated PostgreSQL in production for a payments system.",
    ),
    ("Wrote double-entry ledger code in Python.", "Wrote double-entry ledger code in Python."),
    ("Reduced build time from 20 to 5 minutes.", "Reduced build time from 20 to 5 minutes."),
    ("Cut build time from 20 to 5 minutes.", "Reduced build time from 20 to 5 minutes."),
]


@pytest.mark.parametrize("claim,sentence", PARAPHRASES)
def test_ordinary_paraphrases_are_not_flagged(claim: str, sentence: str) -> None:
    cited = _fact(claim)
    assert check_novel_terms(sentence, [cited], "", claim_words=True).passed
    assert check_numbers(sentence, [cited], "").passed
