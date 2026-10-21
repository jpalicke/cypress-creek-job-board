# ABOUTME: Checks that uncovered posting cues reach the gap report with their original offsets.
# ABOUTME: Uses real pipeline stages and an empty bank so no provider call is needed.
from datetime import UTC, date, datetime

from cypress_creek.config import parse_settings
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import (
    Extractor,
    Importance,
    Posting,
    PostingSource,
    Requirement,
    RequirementKind,
)
from cypress_creek.pipeline.extract import ExtractionResult, ExtractionStatus
from cypress_creek.pipeline.report import GapReport, ReportStatus
from cypress_creek.pipeline.run import assess
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.base import Usage

MODEL = "qwen3.5:0.8b"


def _report(text: str, accepted: list[str]) -> GapReport:
    posting = Posting(
        id="P-1",
        source=PostingSource.PASTE,
        text=text,
        text_hash=text_hash(text),
        extractor=Extractor(name="paste", version="1"),
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    requirements = [
        Requirement(
            id=f"R-{index}",
            text=sentence,
            span=(text.index(sentence), text.index(sentence) + len(sentence)),
            kind=RequirementKind.SKILL,
            term=f"skill-{index}",
            importance=Importance.REQUIRED,
        )
        for index, sentence in enumerate(accepted, start=1)
    ]
    extraction = ExtractionResult(
        status=ExtractionStatus.OK,
        requirements=requirements,
        dropped=[],
        not_assessed_count=0,
        failure=None,
        usage=Usage(input_tokens=1, output_tokens=1),
        prompt_hash="a" * 64,
        schema_version=1,
    )
    provider = OllamaProvider(
        parse_settings({"provider": "ollama", "model": MODEL, "base_url": "http://127.0.0.1:9"})
    )
    return assess(
        posting,
        extraction,
        Bank(facts=[]),
        provider,
        backend="ollama",
        model=MODEL,
        today=date(2024, 6, 1),
    )


def test_skipped_required_sentence_is_reported_without_changing_the_score() -> None:
    accepted = "You must know Python."
    omitted = "Postgres is required."
    prefix = f"Requirements:\n{accepted}\n"
    report = _report(prefix + omitted, [accepted])
    baseline = _report(prefix, [accepted])

    assert report.status is ReportStatus.COMPLETE
    assert [(item.reason, item.text, item.span) for item in report.not_assessed] == [
        ("cue_sentence_uncovered", omitted, (len(prefix), len(prefix) + len(omitted)))
    ]
    assert report.not_assessed_count == 0
    assert report.score == baseline.score


def test_covered_cue_sentences_and_section_headings_are_not_reported() -> None:
    required = "You must know Python."
    preferred = "Experience is preferred."
    text = f"Requirements:\n{required}\nNice to have:\n{preferred}"
    report = _report(text, [required, preferred])

    assert report.not_assessed == []


def test_shared_cues_ignore_case_and_heading_spelling() -> None:
    first = "MUST HAVE Python experience."
    second = "Cloud work is a BONUS."
    text = f"## NICE TO HAVE\n{first}\n{second}"

    report = _report(text, [])

    assert [item.text for item in report.not_assessed] == [first, second]


def test_older_report_payloads_default_to_no_cue_omissions() -> None:
    report = _report("You must know Python.", ["You must know Python."])
    payload = report.model_dump()
    payload.pop("not_assessed", None)

    assert GapReport.model_validate(payload).not_assessed == []
