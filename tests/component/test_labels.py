# ABOUTME: Tests the hand label schema and validator against the real sample bank and planted gaps.
# ABOUTME: Labels feed scoring, so a bad span, fact reference or provenance must fail loudly.
import copy
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from cypress_creek.facts import Bank, load_bank
from evals.harness.labels import (
    LabelError,
    Labels,
    LabelsNotCommitted,
    parse_labels,
    planted_gap_support,
    require_committed_labels,
    validate_labels,
)

ROOT = Path(__file__).parent.parent.parent
BANK = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
PLANTED = planted_gap_support(ROOT / "evals" / "bank" / "PLANTED_GAPS.md")

POSTING = (
    "Data Engineer\n\n"
    "What you will bring\n"
    "Three years of Python experience.\n"
    "Experience with Rust is a plus.\n"
    "Experience with Kubernetes."
)

GOOD: dict[str, Any] = {
    "fixture_id": "unit-test",
    "provenance": {
        "labeled_by": "Claude, on delegation from Joe P (Palicke)",
        "review": "pending",
        "labeled_on": "2026-10-29",
        "model_output_used": False,
    },
    "requirements": [
        {
            "id": "L-1",
            "span": "Three years of Python experience.",
            "kind": "skill",
            "term": "python",
            "years": 3,
            "importance": "required",
            "expected_support": "strong",
            "expected_status": "supported",
            "fact_ids": ["F-0001"],
            "planted_gap": "skill:python:3",
        },
        {
            "id": "L-2",
            "span": "Experience with Rust is a plus.",
            "kind": "skill",
            "term": "rust",
            "importance": "preferred",
            "expected_support": "none",
            "expected_status": "gap",
            "fact_ids": [],
            "planted_gap": "skill:rust",
        },
        {
            "id": "L-3",
            "span": "Experience with Kubernetes.",
            "kind": "skill",
            "term": "kubernetes",
            "importance": "unspecified",
            "expected_support": "partial",
            "expected_status": "gap",
            "fact_ids": ["F-0004"],
            "planted_gap": "skill:kubernetes",
            "note": "Only a familiar level fact.",
        },
    ],
    "cue_sentences": [
        {"span": "Experience with Rust is a plus.", "expected": "covered"},
    ],
}


def labels_with(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(GOOD)
    data.update(changes)
    return data


def edited_requirement(index: int, **changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(GOOD)
    data["requirements"][index].update(changes)
    return data


def problems_for(data: dict[str, Any], posting: str = POSTING, bank: Bank = BANK) -> list[str]:
    labels = parse_labels(data)
    with pytest.raises(LabelError) as caught:
        validate_labels(labels, posting, bank, PLANTED)
    return caught.value.problems


def test_a_label_file_with_an_invalid_span_fails_validation() -> None:
    problems = problems_for(edited_requirement(0, span="Ten years of Python experience."))

    assert problems == ["L-1: span is not an exact substring of the posting"]


def test_a_label_naming_a_fact_that_is_not_in_the_bank_fails_validation() -> None:
    problems = problems_for(edited_requirement(0, fact_ids=["F-9999"]))

    assert problems == ["L-1: fact F-9999 is not in the sample bank"]


def test_a_good_label_file_passes() -> None:
    labels = parse_labels(GOOD)

    validate_labels(labels, POSTING, BANK, PLANTED)

    assert isinstance(labels, Labels)


def test_a_local_only_fact_cannot_be_expected_support() -> None:
    data = edited_requirement(0, fact_ids=["F-0001", "F-0007"], planted_gap=None)

    assert problems_for(data) == ["L-1: fact F-0007 is local only and is never shown to a model"]


def test_an_unverified_fact_cannot_be_expected_support() -> None:
    unverified = load_bank(ROOT / "evals" / "bank" / "sample_bank_unverified.yaml", strict=False)
    both = Bank(facts=[*BANK.facts, *unverified.facts])
    data = edited_requirement(0, fact_ids=["F-0001", "F-0026"], planted_gap=None)

    assert problems_for(data, bank=both) == ["L-1: fact F-0026 is not verified"]


def test_an_unknown_planted_gap_fails_validation() -> None:
    data = edited_requirement(1, planted_gap="skill:cobol")

    assert problems_for(data) == ["L-2: planted gap skill:cobol is not in PLANTED_GAPS.md"]


def test_a_planted_gap_must_agree_with_the_requirement_and_its_support() -> None:
    wrong_support = edited_requirement(2, expected_support="strong", expected_status="supported")
    wrong_term = edited_requirement(1, term="go")

    assert problems_for(wrong_support) == [
        "L-3: planted gap skill:kubernetes expects support partial, not strong"
    ]
    assert problems_for(wrong_term) == [
        "L-2: planted gap skill:rust does not match kind, term, years and issuer of the requirement"
    ]


@pytest.mark.parametrize(
    ("support", "status", "facts"),
    [
        ("strong", "gap", ["F-0001"]),
        ("partial", "supported", ["F-0004"]),
        ("none", "supported", []),
    ],
)
def test_status_is_gap_exactly_when_support_is_not_strong(
    support: str, status: str, facts: list[str]
) -> None:
    data = edited_requirement(
        0, expected_support=support, expected_status=status, fact_ids=facts, planted_gap=None
    )

    assert problems_for(data) == [
        "L-1: expected_status must be gap unless expected_support is strong"
    ]


def test_support_needs_facts_and_a_gap_needs_none() -> None:
    no_facts = edited_requirement(0, fact_ids=[], planted_gap=None)
    facts_for_none = edited_requirement(1, fact_ids=["F-0001"], planted_gap=None)

    assert problems_for(no_facts) == ["L-1: strong or partial support must cite at least one fact"]
    assert problems_for(facts_for_none) == ["L-2: support none must not cite any fact"]


def test_a_cue_sentence_span_must_be_in_the_posting() -> None:
    data = labels_with(
        cue_sentences=[
            {"span": "Experience with Rust is a plus.", "expected": "covered"},
            {"span": "Not here at all.", "expected": "covered"},
        ]
    )

    assert problems_for(data) == ["cue sentence 2: span is not an exact substring of the posting"]


def test_a_posting_sentence_with_a_cue_word_must_be_labeled_as_a_cue_sentence() -> None:
    data = labels_with(cue_sentences=[])

    assert problems_for(data) == [
        "posting sentence with a cue word is not labeled: Experience with Rust is a plus."
    ]


def test_duplicate_requirement_ids_fail_validation() -> None:
    data = copy.deepcopy(GOOD)
    data["requirements"][1]["id"] = "L-1"

    assert problems_for(data) == ["L-1: id is used more than once"]


def test_every_problem_is_reported_not_only_the_first() -> None:
    data = edited_requirement(0, span="Nope.", fact_ids=["F-9999"])

    assert len(problems_for(data)) == 2


def test_provenance_is_required_and_must_say_no_model_output_was_used() -> None:
    missing = copy.deepcopy(GOOD)
    del missing["provenance"]
    used_model = copy.deepcopy(GOOD)
    used_model["provenance"]["model_output_used"] = True

    with pytest.raises(LabelError):
        parse_labels(missing)
    with pytest.raises(LabelError):
        parse_labels(used_model)


def test_unknown_fields_and_bad_enum_values_are_refused() -> None:
    extra = edited_requirement(0, surprise="x")
    bad_kind = edited_requirement(0, kind="vibes")

    for data in (extra, bad_kind):
        with pytest.raises(LabelError):
            parse_labels(data)


def test_a_label_file_with_no_requirements_is_refused() -> None:
    with pytest.raises(LabelError):
        parse_labels(labels_with(requirements=[]))


def test_the_planted_gap_table_is_read_with_its_support() -> None:
    assert PLANTED["skill:python:3"] == "strong"
    assert PLANTED["skill:python:10"] == "partial"
    assert PLANTED["skill:rust"] == "none"
    assert PLANTED["certification:statistics@bogus open courseware"] == "partial"


def git(directory: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=directory,
        check=True,
        capture_output=True,
    )


def test_labels_must_be_committed_before_a_case_may_run(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    labels = fixture / "labels.yaml"

    with pytest.raises(LabelsNotCommitted):
        require_committed_labels(fixture)

    labels.write_text(yaml.safe_dump(GOOD), encoding="utf-8")
    with pytest.raises(LabelsNotCommitted):
        require_committed_labels(fixture)

    git(tmp_path, "add", "fixture/labels.yaml")
    with pytest.raises(LabelsNotCommitted):
        require_committed_labels(fixture)

    git(tmp_path, "commit", "-q", "-m", "labels")
    require_committed_labels(fixture)

    labels.write_text(yaml.safe_dump(GOOD) + "# edited\n", encoding="utf-8")
    with pytest.raises(LabelsNotCommitted):
        require_committed_labels(fixture)
