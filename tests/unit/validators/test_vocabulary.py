# ABOUTME: Tests the closed vocabulary for draft sentences: every word must come from a cited fact.
# ABOUTME: Look-alike letters, invisible characters and unlisted synonyms must fail, not read clean.
import pytest
from builders import fact

from cypress_creek.facts.models import Fact, Level, Tag
from cypress_creek.validators.claims import check_novel_terms
from cypress_creek.validators.vocabulary import (
    FUNCTION_WORDS,
    stem,
    unknown_characters,
    unknown_words,
    vocabulary_words,
)

LED = fact(
    1,
    claim="Led a team of 8 engineers moving a billing system to Python.",
    employer="Initech",
    role="Tech Lead",
    tags=[Tag(name="python", level=Level.EXPERT)],
)
BASE = "Led a team of 8 engineers moving a billing system to Python"


def _verdict(sentence: str, cited: list[Fact] | None = None):  # type: ignore[no-untyped-def]
    return check_novel_terms(sentence, cited or [LED], "", closed_vocabulary=True)


# The classes the reviewer found passing, plus variants of each. None may be clean.
SIBLINGS = [
    # look-alikes and invisible characters
    f"{BASE} for a dеcade.",  # Cyrillic e
    f"{BASE} for a dec​ade.",  # zero width space
    f"{BASE} for a dec­ade.",  # soft hyphen
    f"{BASE} for a dｅcade.",  # full width e
    f"{BASE} for a decadе.",
    f"{BASE} for a dec‍ade.",  # zero width joiner
    # quantity
    f"{BASE} for many years.",
    f"{BASE} for several years.",
    f"{BASE} over multiple years.",
    f"{BASE} used by a lot of customers.",
    f"{BASE} for a decade.",
    f"{BASE} for ten-plus years.",
    # impact
    f"{BASE}, halving latency.",
    f"{BASE}, the first in the industry.",
    f"{BASE}, earning a promotion.",
    f"{BASE}, which was rolled back.",
    f"{BASE}, doubling revenue.",
    f"{BASE}, cutting costs.",
    # rank and role
    f"{BASE}, spearheading the effort.",
    f"{BASE} as head of engineering.",
    f"{BASE} single handedly.",
    f"{BASE} solo.",
    f"{BASE} as the founder.",
    f"{BASE} as engineering manager.",
    "Led a team of 8 senior staff engineers moving a billing system to Python.",
    # negation
    "Hardly led a team of 8 engineers moving a billing system to Python.",
    f"{BASE}, but dont mention it.",
    f"{BASE}, away from Python.",
    "Never led a team of 8 engineers moving a billing system to Python.",
    # plural inflation and passive role inversion
    "Led teams of 8 engineers moving billing systems to Python.",
    "Led a team of 8 engineers moving billing systems to Python.",
    "Was led by a team of 8 engineers moving a billing system to Python.",
    "Python was moved by a team of 8 engineers led.",
    # hyphenation, plurals, possessives, punctuation tricks
    f"{BASE}, world-class.",
    f"{BASE}; owner's mindset.",
    f"{BASE} — award-winning.",
]


@pytest.mark.parametrize("sentence", SIBLINGS)
def test_siblings_are_never_clean(sentence: str) -> None:
    verdict = _verdict(sentence)
    assert not verdict.passed, sentence
    assert verdict.validator == "V10"


def test_the_look_alike_letter_is_named_by_code_point() -> None:
    verdict = _verdict(f"{BASE} for a dеcade.")
    assert verdict.offending is not None


def test_a_non_ascii_letter_that_a_cited_fact_has_is_allowed() -> None:
    cafe = fact(2, claim="Ran the café reporting system.", employer="Initech", role="Engineer")
    assert _verdict("Ran the café reporting system.", [cafe]).passed
    assert not _verdict(
        "Ran the café reporting system.", [fact(3, claim="Ran the reporting system.")]
    ).passed


# Honest rewordings that only reuse the fact's words stay clean.
CLEAN = [
    BASE + ".",
    "Led a team of eight engineers moving a billing system to Python.",
    "Moving a billing system to Python, led a team of 8 engineers.",
    "Tech Lead, and the team of 8 engineers moving the billing system to Python.",
    "Led the 8 engineers' move of a billing system to Python.",
    "Led a team of 8 engineers who moved a billing system to Python at Initech.",
    "led a team of 8 engineers moving a billing system to python",
    "LED A TEAM OF 8 ENGINEERS MOVING A BILLING SYSTEM TO PYTHON!",
    "Tech Lead at Initech: led a team of 8 engineers.",
    "Billing-system: led a team of 8 engineers moving to Python.",
]


@pytest.mark.parametrize("sentence", CLEAN)
def test_reusing_the_facts_words_stays_clean(sentence: str) -> None:
    assert _verdict(sentence).passed, sentence


def test_months_and_numbers_are_left_to_v7_and_v8() -> None:
    assert _verdict("Led a team of 8 engineers in March 2022.").passed
    assert "march" not in unknown_words("In March 2022 and twelve more.", ["March 2022"])


def test_the_requirement_text_counts_only_when_a_caller_passes_it() -> None:
    sentence = "Led Kubernetes work."
    assert not check_novel_terms(sentence, [LED], "", closed_vocabulary=True).passed
    with_requirement = check_novel_terms(sentence, [LED], "Kubernetes work", closed_vocabulary=True)
    assert with_requirement.passed
    assert check_novel_terms("Led a team of 8 engineers.", [LED], "", closed_vocabulary=True).passed


def test_the_default_check_is_unchanged() -> None:
    assert check_novel_terms("Led spearheading senior hardly", [LED], "").passed


def test_a_dropped_negation_is_still_flagged() -> None:
    cited = fact(
        4, claim="Never missed a release date in 3 years.", employer="Initech", role="Engineer"
    )
    verdict = _verdict("Missed a release date in 3 years.", [cited])
    assert not verdict.passed
    assert verdict.offending == "negation dropped"
    assert _verdict("Never missed a release date in 3 years.", [cited]).passed


@pytest.mark.parametrize(
    "word,expected",
    [
        ("services", "services"),
        ("service", "servic"),
        ("migrating", "migrat"),
        ("migrated", "migrat"),
        ("migrate", "migrat"),
        ("running", "run"),
        ("run", "run"),
        ("companies", "companies"),
        ("company", "company"),
        ("led", "led"),
        ("lead", "lead"),
        ("python", "python"),
        ("is", "is"),
        ("teams", "teams"),
        ("team", "team"),
    ],
)
def test_stem_is_a_small_explicit_inflection_rule(word: str, expected: str) -> None:
    assert stem(word) == expected


def test_a_stem_never_joins_words_that_mean_different_things() -> None:
    assert stem("manager") != stem("manage")
    assert stem("lead") != stem("led")
    assert stem("developer") != stem("developed")


def test_a_plural_is_a_different_word_unless_a_fact_has_that_plural() -> None:
    assert unknown_words("teams", ["Led a team"]) == ["teams"]
    assert unknown_words("teams", ["Led two teams"]) == []
    assert unknown_words("team", ["Led two teams"]) == ["team"]


def test_by_is_not_a_free_word_so_a_passive_cannot_swap_who_led_whom() -> None:
    assert "by" not in FUNCTION_WORDS
    assert unknown_words("led by a team", ["Led a team"]) == ["by"]
    assert unknown_words("run by another team", ["run by another team"]) == []


def test_a_recombination_of_a_facts_own_words_is_a_documented_limit() -> None:
    # Every word is in the fact, so the closed vocabulary cannot see that the meaning changed.
    assert _verdict("Led 8 billing system.").passed
    assert _verdict("A team led 8 engineers.").passed


def test_the_function_word_list_is_the_reviewed_one() -> None:
    assert (
        frozenset(
            {
                "a",
                "an",
                "the",
                "of",
                "to",
                "in",
                "on",
                "at",
                "for",
                "with",
                "and",
                "as",
                "from",
                "using",
                "while",
                "its",
                "their",
                "into",
                "that",
                "which",
                "who",
                "was",
                "were",
                "is",
                "are",
                "been",
                "it",
                "this",
                "these",
                "those",
                "through",
                "via",
            }
        )
        == FUNCTION_WORDS
    )
    for claim_word in ("no", "not", "never", "only", "first", "more", "most", "all", "every"):
        assert claim_word not in FUNCTION_WORDS


def test_vocabulary_words_come_from_every_text_given() -> None:
    assert {"led", "team"} <= vocabulary_words(["Led a team", "Python"])
    assert vocabulary_words([]) == set()


def test_unknown_characters_are_any_non_ascii_character_no_fact_has() -> None:
    assert unknown_characters("d\u0435cade", ["decade"]) == {"\u0435"}
    assert unknown_characters("dec\u200bade", ["decade"]) == {"\u200b"}
    assert unknown_characters("\uff2c\uff25\uff24", ["LED"]) == {"\uff2c", "\uff25", "\uff24"}
    assert unknown_characters("caf\u00e9", ["caf\u00e9"]) == set()
    assert unknown_characters("plain ascii", [""]) == set()


def test_a_fact_word_with_a_ligature_or_soft_hyphen_still_matches_its_plain_spelling() -> None:
    assert unknown_words("financial services", ["\ufb01nancial ser\u00advices"]) == []


def test_a_fact_word_in_full_width_letters_matches_its_plain_spelling() -> None:
    assert unknown_words("led team", ["\uff2c\uff25\uff24 team"]) == []
