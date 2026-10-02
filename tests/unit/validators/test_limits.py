# ABOUTME: Tests V11 requirement cap and dedupe, V12 date sanity and V13 cue sentence coverage.
# ABOUTME: V11 also has Hypothesis properties, since it must hold for any list of requirements.
from datetime import date

from builders import fact, requirement, span_of
from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.ingest.models import Requirement
from cypress_creek.validators.fact_dates import check_fact_dates
from cypress_creek.validators.requirements import (
    MAX_REQUIREMENTS,
    check_cue_coverage,
    check_requirement_cap,
    dedupe_requirements,
    uncovered_cue_sentences,
)

TODAY = date(2026, 10, 2)


def _requirement_with_term(term: str, n: int = 1) -> Requirement:
    return requirement(term="x").model_copy(update={"term": term, "id": f"R-{n}"})


def test_v11_dedupes_on_normalized_term_keeping_the_first() -> None:
    first = _requirement_with_term("PostgreSQL", 1)
    second = _requirement_with_term(" postgresql. ", 2)
    other = _requirement_with_term("kubernetes", 3)
    assert dedupe_requirements([first, second, other]) == [first, other]


def test_v11_caps_the_list() -> None:
    many = [_requirement_with_term(f"skill{n}", n) for n in range(MAX_REQUIREMENTS + 10)]
    assert len(dedupe_requirements(many)) == MAX_REQUIREMENTS


def test_v11_accepts_a_list_within_the_cap_with_unique_terms() -> None:
    assert check_requirement_cap([_requirement_with_term("a", 1), _requirement_with_term("b", 2)])


def test_v11_rejects_more_than_the_cap() -> None:
    many = [_requirement_with_term(f"skill{n}", n) for n in range(MAX_REQUIREMENTS + 1)]
    verdict = check_requirement_cap(many)
    assert not verdict.passed
    assert verdict.validator == "V11"


def test_v11_rejects_a_duplicate_term() -> None:
    verdict = check_requirement_cap(
        [_requirement_with_term("Python", 1), _requirement_with_term("python ", 2)]
    )
    assert not verdict.passed
    assert verdict.offending == "python"


@given(
    st.lists(
        st.sampled_from(["a", "A", "b", " b ", "c.", "d", "e"] + list("fghijkl")), max_size=120
    )
)
def test_v11_dedupe_is_idempotent_capped_and_unique(terms: list[str]) -> None:
    reqs = [_requirement_with_term(term, n) for n, term in enumerate(terms)]
    once = dedupe_requirements(reqs)
    assert dedupe_requirements(once) == once
    assert len(once) <= MAX_REQUIREMENTS
    assert check_requirement_cap(once).passed


@given(st.lists(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ", min_size=1), max_size=80))
def test_v11_dedupe_never_adds_or_reorders(terms: list[str]) -> None:
    reqs = [_requirement_with_term(term, n) for n, term in enumerate(terms) if term.strip()]
    kept = dedupe_requirements(reqs)
    positions = [reqs.index(item) for item in kept]
    assert positions == sorted(positions)


def test_v12_accepts_sane_dates() -> None:
    assert check_fact_dates(fact(1), TODAY).passed


def test_v12_rejects_a_future_start() -> None:
    verdict = check_fact_dates(fact(1, start=date(2027, 1, 1), end=None), TODAY)
    assert not verdict.passed
    assert verdict.validator == "V12"
    assert verdict.offending == "start"


def test_v12_rejects_start_after_end() -> None:
    verdict = check_fact_dates(fact(1, start=date(2023, 1, 1), end=date(2020, 1, 1)), TODAY)
    assert not verdict.passed


def test_v12_rejects_a_future_verification_date() -> None:
    future = fact(1).model_copy(update={"verified_on": date(2030, 1, 1)})
    verdict = check_fact_dates(future, TODAY)
    assert not verdict.passed
    assert verdict.offending == "verified_on"


CUE_POSTING = "Requirements:\n- You must know Python.\n- Postgres is required.\nWe are friendly.\n"
PYTHON_SPAN = span_of(CUE_POSTING, "You must know Python")
POSTGRES_SPAN = span_of(CUE_POSTING, "Postgres is required")


def test_v13_accepts_when_every_cue_sentence_is_covered() -> None:
    assert uncovered_cue_sentences(CUE_POSTING, [PYTHON_SPAN, POSTGRES_SPAN]) == []


def test_v13_reports_a_cue_sentence_with_no_requirement() -> None:
    assert uncovered_cue_sentences(CUE_POSTING, [PYTHON_SPAN]) == ["- Postgres is required."]


def test_v13_ignores_sentences_without_cues_and_cue_headings() -> None:
    assert uncovered_cue_sentences("Nice to have:\nWe are a friendly team.", []) == []


def test_v13_a_partial_overlap_counts_as_covered() -> None:
    assert uncovered_cue_sentences("You must know Python well.", [(9, 15)]) == []


def test_v13_verdict_names_the_first_uncovered_sentence() -> None:
    verdict = check_cue_coverage(CUE_POSTING, [])
    assert not verdict.passed
    assert verdict.validator == "V13"
    assert verdict.offending == "- You must know Python."


def test_v13_verdict_passes_with_full_coverage() -> None:
    reqs = [
        requirement("You must know Python", posting=CUE_POSTING),
        requirement("Postgres is required", posting=CUE_POSTING, id="R-2"),
    ]
    assert check_cue_coverage(CUE_POSTING, reqs).passed
