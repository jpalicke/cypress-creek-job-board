# ABOUTME: Tests V1 (schema), V2 (verbatim span), V3 (importance cues) and the shared cue module.
# ABOUTME: Includes Hypothesis properties for span checks at string and unicode boundaries.
import json

import pytest
from builders import POSTING, requirement, span_of
from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.ingest.models import Importance, Requirement
from cypress_creek.validators.cues import cue_importance, has_cue, split_sentences
from cypress_creek.validators.extraction import (
    check_importance,
    check_schema,
    check_verbatim_span,
)

VALID = {
    "id": "R-1",
    "text": "Postgres",
    "span": [0, 8],
    "kind": "skill",
    "term": "postgres",
    "importance": "required",
}


def test_v1_accepts_conforming_json_text() -> None:
    verdict = check_schema(Requirement, json.dumps(VALID))
    assert verdict.passed and verdict.validator == "V1"


def test_v1_accepts_a_conforming_mapping() -> None:
    assert check_schema(Requirement, VALID).passed


@pytest.mark.parametrize(
    "hostile",
    [
        "not json at all",
        "",
        "[]",
        json.dumps({**VALID, "extra": "x"}),
        json.dumps({**VALID, "kind": "wizard"}),
        json.dumps({**VALID, "span": [5, 2]}),
        json.dumps({**VALID, "years": "five"}),
        json.dumps({k: v for k, v in VALID.items() if k != "id"}),
    ],
)
def test_v1_rejects_malformed_or_extra_field_output(hostile: str) -> None:
    verdict = check_schema(Requirement, hostile)
    assert not verdict.passed
    assert verdict.reason


def test_v1_rejects_a_mapping_with_extra_fields() -> None:
    assert not check_schema(Requirement, {**VALID, "extra": 1}).passed


def test_v2_accepts_the_exact_posting_slice() -> None:
    assert check_verbatim_span(POSTING, requirement()).passed


def test_v2_rejects_an_altered_requirement() -> None:
    altered = requirement().model_copy(update={"text": "6 years of Postgres experience"})
    verdict = check_verbatim_span(POSTING, altered)
    assert not verdict.passed
    assert verdict.offending == "6 years of Postgres experience"


def test_v2_rejects_a_span_past_the_end() -> None:
    off_end = requirement().model_copy(update={"span": (0, len(POSTING) + 5)})
    assert not check_verbatim_span(POSTING, off_end).passed


def test_v2_rejects_a_unicode_lookalike() -> None:
    posting = "Postgres required"
    lookalike = Requirement(
        id="R-1",
        text="Pоstgres",
        span=(0, 8),
        kind="skill",  # type: ignore[arg-type]
        term="postgres",
        importance=Importance.UNSPECIFIED,
    )
    assert not check_verbatim_span(posting, lookalike).passed


@given(
    text=st.text(min_size=1, max_size=60),
    data=st.data(),
)
def test_v2_property_exact_slices_pass_and_altered_slices_fail(
    text: str, data: st.DataObject
) -> None:
    start = data.draw(st.integers(min_value=0, max_value=len(text) - 1))
    end = data.draw(st.integers(min_value=start + 1, max_value=len(text)))
    exact = Requirement(
        id="R-1",
        text=text[start:end],
        span=(start, end),
        kind="skill",  # type: ignore[arg-type]
        term="x",
        importance=Importance.UNSPECIFIED,
    )
    assert check_verbatim_span(text, exact).passed
    altered = exact.model_copy(update={"text": exact.text + "!"})
    assert not check_verbatim_span(text, altered).passed


def test_v3_accepts_importance_matching_the_cues() -> None:
    assert check_importance(POSTING, requirement()).passed
    plus = requirement("Kubernetes experience is a plus", importance=Importance.PREFERRED)
    assert check_importance(POSTING, plus).passed


def test_v3_rejects_a_demoted_requirement() -> None:
    demoted = requirement(importance=Importance.PREFERRED)
    verdict = check_importance(POSTING, demoted)
    assert not verdict.passed
    assert "required" in verdict.reason


def test_v3_rejects_importance_where_no_cue_exists() -> None:
    posting = "We build things. Python is used here."
    req = requirement("Python is used here", posting=posting, importance=Importance.REQUIRED)
    assert not check_importance(posting, req).passed
    unspecified = requirement(
        "Python is used here", posting=posting, importance=Importance.UNSPECIFIED
    )
    assert check_importance(posting, unspecified).passed


def test_cue_in_the_sentence_wins_over_the_section_heading() -> None:
    posting = "Requirements:\n- Rust is preferred.\n"
    assert cue_importance(posting, span_of(posting, "Rust is preferred")) == Importance.PREFERRED


def test_a_sentence_with_conflicting_cues_is_unspecified() -> None:
    posting = "You must know Go, Rust is preferred."
    assert cue_importance(posting, span_of(posting, "You must know Go")) == Importance.UNSPECIFIED


def test_unrelated_heading_resets_the_section() -> None:
    posting = "Requirements:\n- Go\nBenefits:\n- Free snacks\n"
    assert cue_importance(posting, span_of(posting, "Go")) == Importance.REQUIRED
    assert cue_importance(posting, span_of(posting, "Free snacks")) == Importance.UNSPECIFIED


def test_cues_match_whole_words_only() -> None:
    posting = "Mustard is a condiment and requirements are boring."
    assert cue_importance(posting, (0, 7)) == Importance.UNSPECIFIED


def test_split_sentences_handles_lines_and_punctuation() -> None:
    text = "One. Two!\n\n- Three?  Four"
    parts = [text[s:e] for s, e in split_sentences(text)]
    assert parts == ["One.", "Two!", "- Three?", "Four"]


def test_span_outside_the_text_is_clamped_not_crashed() -> None:
    assert cue_importance("must", (0, 99)) == Importance.REQUIRED


def test_markdown_and_preferred_headings_set_the_section() -> None:
    posting = "## Nice to have\nRust\n\n# Requirements\nGo\n"
    assert cue_importance(posting, span_of(posting, "Rust")) == Importance.PREFERRED
    assert cue_importance(posting, span_of(posting, "Go")) == Importance.REQUIRED


def test_blank_and_bare_lines_are_not_headings() -> None:
    posting = "\n   \nWe use Go every day\nRust"
    assert cue_importance(posting, span_of(posting, "Rust")) == Importance.UNSPECIFIED


def test_has_cue_finds_required_and_preferred_words() -> None:
    assert has_cue("You must know SQL")
    assert has_cue("Docker is a plus")
    assert not has_cue("We value teamwork")


def test_a_span_sitting_in_a_preferred_sentence_is_preferred() -> None:
    posting = "Docker is a plus."
    assert cue_importance(posting, (0, 6)) == Importance.PREFERRED
