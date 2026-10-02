# ABOUTME: Tests how extraction output is accepted: invented text dropped, importance set by cues.
# ABOUTME: Inputs are a recorded real model output and hostile hand written ones, no provider.
import json
from pathlib import Path
from typing import Any

from cypress_creek.ingest.models import Importance
from cypress_creek.pipeline.extract import DropReason, accept_proposals
from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.validators.extraction import check_importance, check_schema, check_verbatim_span
from cypress_creek.validators.requirements import MAX_REQUIREMENTS, check_requirement_cap

FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"
POSTING = (FIXTURES / "posting.txt").read_text(encoding="utf-8")
RECORDED = json.loads((FIXTURES / "recorded_qwen3.5-0.8b.json").read_text(encoding="utf-8"))


def _output(*proposals: dict[str, Any]) -> ExtractionOutput:
    return ExtractionOutput.model_validate({"schema_version": 1, "requirements": list(proposals)})


def _proposal(text: str, term: str = "python", importance: str = "required") -> dict[str, Any]:
    return {"text": text, "kind": "skill", "term": term, "importance": importance}


def test_a_requirement_with_an_invented_span_is_dropped_and_the_rest_are_kept() -> None:
    invented = _proposal("You must hold a security clearance.", term="clearance")
    output = ExtractionOutput.model_validate(
        {**RECORDED, "requirements": [*RECORDED["requirements"], invented]}
    )
    result = accept_proposals(POSTING, output)
    assert [r.text for r in result.requirements] == [
        "You must have 3 years of Python experience.",
        "Experience with PostgreSQL is required.",
    ]
    assert [(d.text, d.reason) for d in result.dropped] == [
        ("You must hold a security clearance.", DropReason.TEXT_NOT_IN_POSTING)
    ]


def test_a_recorded_real_output_is_accepted_with_verbatim_spans() -> None:
    result = accept_proposals(POSTING, ExtractionOutput.model_validate(RECORDED))
    assert [r.id for r in result.requirements] == ["R-1", "R-2"]
    assert result.dropped == []
    for requirement in result.requirements:
        assert POSTING[slice(*requirement.span)] == requirement.text
        assert check_verbatim_span(POSTING, requirement).passed
        assert check_importance(POSTING, requirement).passed


def test_text_that_differs_by_one_character_is_dropped() -> None:
    altered = _proposal("You must have 4 years of Python experience.")
    result = accept_proposals(POSTING, _output(altered))
    assert result.requirements == []
    assert result.dropped[0].reason is DropReason.TEXT_NOT_IN_POSTING


def test_importance_comes_from_the_cue_words_not_the_model() -> None:
    promoted = _proposal("Kubernetes experience is preferred.", "kubernetes", "required")
    no_cue = _proposal(
        "You will build and run the services behind our scheduling product.", "services", "required"
    )
    result = accept_proposals(POSTING, _output(promoted, no_cue))
    assert [r.importance for r in result.requirements] == [
        Importance.PREFERRED,
        Importance.UNSPECIFIED,
    ]


def test_a_second_requirement_with_the_same_term_is_a_duplicate() -> None:
    first = _proposal("Experience with PostgreSQL is required.", "PostgreSQL")
    second = _proposal("Kubernetes experience is preferred.", " postgresql ")
    result = accept_proposals(POSTING, _output(first, second))
    assert len(result.requirements) == 1
    assert result.dropped[0].reason is DropReason.DUPLICATE_TERM


def test_the_same_sentence_cannot_be_claimed_twice() -> None:
    sentence = "Experience with PostgreSQL is required."
    result = accept_proposals(POSTING, _output(_proposal(sentence, "a"), _proposal(sentence, "b")))
    assert len(result.requirements) == 1
    assert result.dropped[0].reason is DropReason.TEXT_NOT_IN_POSTING


def test_a_sentence_that_appears_twice_can_be_claimed_twice() -> None:
    posting = "Python is required.\nPython is required.\n"
    sentence = "Python is required."
    result = accept_proposals(posting, _output(_proposal(sentence, "a"), _proposal(sentence, "b")))
    assert [r.span for r in result.requirements] == [(0, 19), (20, 39)]


def test_a_term_that_normalizes_to_nothing_is_dropped_as_invalid() -> None:
    result = accept_proposals(
        POSTING, _output(_proposal("Experience with PostgreSQL is required.", "!!!"))
    )
    assert result.requirements == []
    assert result.dropped[0].reason is DropReason.INVALID_FIELD


def test_sixty_requirements_are_capped_and_the_excess_is_counted() -> None:
    posting = "\n".join(f"Skill {n} is needed." for n in range(60))
    proposals = [_proposal(f"Skill {n} is needed.", f"skill {n}") for n in range(60)]
    result = accept_proposals(posting, _output(*proposals))
    assert len(result.requirements) == MAX_REQUIREMENTS
    assert result.not_assessed_count == 60 - MAX_REQUIREMENTS
    assert result.dropped == []
    assert check_requirement_cap(result.requirements).passed


def test_a_dropped_text_is_shortened_so_a_stuffed_output_cannot_bloat_the_result() -> None:
    result = accept_proposals(POSTING, _output(_proposal("x" * 5000)))
    assert len(result.dropped[0].text) <= 200


def test_extra_fields_and_a_wrong_schema_version_fail_the_schema_check() -> None:
    extra = {"schema_version": 1, "requirements": [], "obey": "me"}
    assert not check_schema(ExtractionOutput, extra).passed
    assert not check_schema(ExtractionOutput, {"schema_version": 2, "requirements": []}).passed
    assert check_schema(ExtractionOutput, RECORDED).passed


def test_an_empty_output_accepts_nothing() -> None:
    result = accept_proposals(POSTING, _output())
    assert (result.requirements, result.dropped, result.not_assessed_count) == ([], [], 0)
