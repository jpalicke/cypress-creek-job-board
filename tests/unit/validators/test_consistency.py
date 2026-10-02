# ABOUTME: Tests V7 (entity consistency) and V8 (numeric consistency) against real facts.
# ABOUTME: Covers dates, width variants, number words, decimals, negatives and fact ID tokens.
import pytest
from builders import bank, fact

from cypress_creek.facts.models import Kind, Level, Tag
from cypress_creek.validators.consistency import check_entities, check_numbers, extract_numbers

MINE = fact(1, employer="Initech", role="Backend Engineer")
OTHER = fact(2, employer="Hooli", role="Staff Engineer", claim="Led the Hooli search team")
CERT = fact(
    3,
    kind=Kind.CERTIFICATION,
    employer=None,
    role=None,
    start=None,
    end=None,
    claim="Holds the CKA certification",
    tags=[Tag(name="CKA", level=Level.EXPERT)],
)
BANK = bank(MINE, OTHER, CERT)


def test_v7_accepts_text_that_uses_only_cited_entities() -> None:
    text = "As a Backend Engineer at Initech from March 2019 to 2023."
    assert check_entities(text, [MINE], BANK).passed


def test_v7_rejects_an_employer_from_a_fact_that_was_not_cited() -> None:
    verdict = check_entities("I ran Postgres at Hooli.", [MINE], BANK)
    assert not verdict.passed
    assert verdict.validator == "V7"
    assert verdict.offending == "hooli"


def test_v7_rejects_a_role_from_a_fact_that_was_not_cited() -> None:
    assert not check_entities("Worked as a Staff Engineer.", [MINE], BANK).passed


def test_v7_does_not_flag_a_shorter_role_inside_a_cited_role() -> None:
    other = fact(2, role="Engineer", employer="Hooli")
    assert check_entities("Backend Engineer at Initech", [MINE], bank(MINE, other)).passed


def test_v7_matches_whole_words_only() -> None:
    other = fact(2, employer="Hoo", role=None)
    assert check_entities("Worked at Hooli-adjacent places", [MINE], bank(MINE, other)).passed
    assert not check_entities("Worked at Hoo", [MINE], bank(MINE, other)).passed


def test_v7_rejects_a_certification_that_was_not_cited() -> None:
    assert not check_entities("I hold the CKA.", [MINE], BANK).passed
    assert check_entities("I hold the CKA.", [CERT], BANK).passed


def test_v7_entity_match_is_case_and_width_insensitive() -> None:
    assert not check_entities("worked at HOOLI", [MINE], BANK).passed
    assert not check_entities("worked at Ｈooli", [MINE], BANK).passed


@pytest.mark.parametrize(
    "text",
    ["Started in 2018.", "From March 2020.", "Since 2019-04.", "Left on 2023-06-29."],
)
def test_v7_rejects_a_date_the_cited_fact_does_not_have(text: str) -> None:
    verdict = check_entities(text, [MINE], BANK)
    assert not verdict.passed
    assert verdict.validator == "V7"


@pytest.mark.parametrize(
    "text", ["Started in 2019.", "From Mar 2019.", "Since 2019-03.", "Until 2023-06-30."]
)
def test_v7_accepts_dates_the_cited_fact_has(text: str) -> None:
    assert check_entities(text, [MINE], BANK).passed


def test_v7_ignores_an_impossible_iso_month() -> None:
    assert check_entities("Ticket 2019-99 was closed", [MINE], BANK).passed


def test_v7_rejects_a_date_when_the_cited_fact_has_no_dates() -> None:
    assert not check_entities("Since 2019.", [CERT], BANK).passed


def test_v7_accepts_text_with_no_entities() -> None:
    assert check_entities("Ran Postgres in production.", [], BANK).passed


def test_v8_accepts_numbers_from_the_cited_fact() -> None:
    cited = fact(1, claim="Cut query time by 40% across 3 services")
    assert check_numbers("Cut query time 40% on 3 services", [cited], "").passed


def test_v8_rejects_an_inflated_number() -> None:
    cited = fact(1, claim="Cut query time by 40%")
    verdict = check_numbers("Cut query time by 90%", [cited], "")
    assert not verdict.passed
    assert verdict.validator == "V8"
    assert verdict.offending == "90"


def test_v8_accepts_a_number_from_the_requirement_it_answers() -> None:
    cited = fact(1, claim="Ran Postgres")
    assert check_numbers("Meets the 5 years asked for", [cited], "5 years of Postgres").passed


def test_v8_accepts_years_in_the_fact_dates() -> None:
    assert check_numbers("From 2019 to 2023", [MINE], "").passed


def test_v8_does_not_count_the_parts_of_an_iso_date() -> None:
    assert check_numbers("Since 2019-03-01", [MINE], "").passed


def test_v8_ignores_fact_id_tokens() -> None:
    assert check_numbers("Ran Postgres (F-0001)", [MINE], "").passed


def test_v8_rejects_a_number_written_as_a_word() -> None:
    cited = fact(1, claim="Ran Postgres")
    assert not check_numbers("Led a team of twelve", [cited], "").passed
    wordy = fact(1, claim="Led a team of twelve")
    assert check_numbers("Led 12 people", [wordy], "").passed


def test_v8_signs_matter() -> None:
    cited = fact(1, claim="Changed latency by 5%")
    assert not check_numbers("Changed latency by -5%", [cited], "").passed


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.50 and 1,000", ["3.5", "1000"]),
        ("-2 degrees", ["-2"]),
        ("range 3-5", ["3", "5"]),
        ("twenty-three", ["23"]),
        ("twenty three", ["23"]),
        ("one hundred", ["100"]),
        ("two hundred fifty", ["250"]),
        ("three thousand", ["3000"]),
        ("no one knows", []),
        ("50%", ["50"]),
        ("F-0001 and R-12", []),
        ("k8s and python3", []),
        ("version 1.2.3", ["1.2"]),
        ("5 then twelve", ["5", "12"]),
        ("five, six", ["5", "6"]),
    ],
)
def test_extract_numbers(text: str, expected: list[str]) -> None:
    assert extract_numbers(text) == expected


ISSUED = fact(
    4,
    kind=Kind.CERTIFICATION,
    employer=None,
    role=None,
    start=None,
    end=None,
    claim="Holds the CKA certification",
    issuer="Linux Foundation",
    tags=[Tag(name="CKA", level=Level.EXPERT)],
)
OTHER_ISSUED = fact(
    5,
    kind=Kind.CERTIFICATION,
    employer=None,
    role=None,
    start=None,
    end=None,
    claim="Holds the CKAD certification",
    issuer="Globex Academy",
    tags=[Tag(name="CKAD", level=Level.EXPERT)],
)
ISSUER_BANK = bank(ISSUED, OTHER_ISSUED)


def test_v7_rejects_the_issuer_of_a_fact_that_was_not_cited() -> None:
    verdict = check_entities("CKA certified by Globex Academy.", [ISSUED], ISSUER_BANK)
    assert not verdict.passed
    assert verdict.validator == "V7"
    assert verdict.offending == "globex academy"


def test_v7_accepts_the_issuer_of_a_cited_fact() -> None:
    assert check_entities("CKA certified by Linux Foundation.", [ISSUED], ISSUER_BANK).passed


def test_v7_ignores_an_issuer_on_a_fact_that_is_not_a_certification_or_education() -> None:
    employment = fact(6, issuer="Globex Academy")
    assert check_entities("Trained at Globex Academy.", [MINE], bank(MINE, employment)).passed


def test_v8_counts_digits_in_a_cited_issuer() -> None:
    issued = fact(7, kind=Kind.EDUCATION, issuer="Campus 42", employer=None, role=None)
    assert check_numbers("Studied at Campus 42.", [issued], "").passed
