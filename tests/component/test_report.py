# ABOUTME: Tests report assembly: the gap list, the score, incomplete modes and citation refusal.
# ABOUTME: Stage outputs are real objects over a fictional bank, and hostile ones are hand built.
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cypress_creek.config import parse_settings
from cypress_creek.facts import load_bank
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
from cypress_creek.pipeline.entail import EntailedMatch, Entailment, entail, judge
from cypress_creek.pipeline.extract import ExtractionResult, ExtractionStatus, finish_extraction
from cypress_creek.pipeline.report import (
    TRIAGE_DISCLAIMER,
    GapReport,
    Provenance,
    ReportRefused,
    ReportStatus,
    build_report,
    verify_report,
)
from cypress_creek.pipeline.retrieve import RequirementCandidates, retrieve
from cypress_creek.pipeline.schemas import EntailmentOutput, EntailmentVerdict, ExtractionOutput
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.base import Capabilities, CostPerMtok, Usage
from cypress_creek.scoring.aliases import load_aliases
from cypress_creek.scoring.support import Gate, Support

FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"
FREE = CostPerMtok(input=0, output=0)
LOCAL = Capabilities(context_tokens=8192, strict_schema=True, local=True, cost_per_mtok=FREE)
TODAY = date(2024, 6, 1)
# Nothing listens on the discard port. A call that reached the network is ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"

BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 4 years.
    kind: project
    start: 2019-01-01
    end: 2023-01-01
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
  - id: F-0002
    claim: Operated a fictional PostgreSQL cluster.
    kind: project
    tags: [{name: postgresql, level: familiar}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/b"}
    share: shareable
  - id: F-0003
    claim: Claimed Go work with no verification.
    kind: project
    tags: [{name: go, level: expert}]
    evidence: {type: self_attested, pointer: notes}
    share: shareable
"""
POSTING_TEXT = (FIXTURES / "posting.txt").read_text(encoding="utf-8")
POSTING = Posting(
    id="P-1",
    source=PostingSource.PASTE,
    text=POSTING_TEXT,
    text_hash=text_hash(POSTING_TEXT),
    extractor=Extractor(name="paste", version="1"),
    created_at=datetime(2024, 6, 1, tzinfo=UTC),
)
PROVENANCE = Provenance(
    backend="ollama",
    model="qwen3.5:0.8b",
    run_id="run-1",
    prompt_hashes={"extract": "a" * 64, "entail": "b" * 64},
    usage=Usage(input_tokens=900, output_tokens=120),
)


def _requirement(
    n: int, term: str, importance: Importance, years: int | None = None
) -> Requirement:
    return Requirement(
        id=f"R-{n}",
        text=f"Needs {term}.",
        span=(0, 10),
        kind=RequirementKind.SKILL,
        term=term,
        years=years,
        importance=importance,
    )


REQUIREMENTS = [
    _requirement(1, "python", Importance.REQUIRED, years=3),
    _requirement(2, "postgresql", Importance.REQUIRED),
    _requirement(3, "kubernetes", Importance.PREFERRED),
]


def _extraction(requirements: list[Requirement]) -> ExtractionResult:
    return ExtractionResult(
        status=ExtractionStatus.OK,
        requirements=requirements,
        dropped=[],
        not_assessed_count=0,
        failure=None,
        usage=Usage(input_tokens=500, output_tokens=60),
        prompt_hash="a" * 64,
        schema_version=1,
    )


@pytest.fixture
def bank(tmp_path: Path) -> Bank:
    path = tmp_path / "bank.yaml"
    path.write_text(BANK, encoding="utf8")
    return load_bank(path)


def _unreachable_provider() -> OllamaProvider:
    return OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": "qwen3.5:0.8b", "base_url": NOTHING_LISTENING}
        )
    )


def _answer(verdict: EntailmentVerdict, fact: str, rationale: str) -> EntailmentOutput:
    return EntailmentOutput(schema_version=1, verdict=verdict, fact_ids=[fact], rationale=rationale)


def _stages(
    bank: Bank, requirements: list[Requirement]
) -> tuple[list[RequirementCandidates], list[EntailedMatch]]:
    """Real retrieval, then the judge on hand written answers, and a real gap through entail."""
    candidates = retrieve(requirements, bank, LOCAL, TODAY, load_aliases())
    answers = {
        "R-1": _answer(EntailmentVerdict.SUPPORTS, "F-0001", "F-0001 shows Python work."),
        "R-2": _answer(EntailmentVerdict.PARTIAL, "F-0002", "F-0002 shows PostgreSQL work."),
    }
    by_requirement = {r.id: r for r in requirements}
    entailed = [
        judge(
            answers[c.requirement_id],
            by_requirement[c.requirement_id],
            c.fact_ids,
            c.support,
            bank,
            LOCAL,
        )
        if not c.is_gap
        else entail(by_requirement[c.requirement_id], c, bank, _unreachable_provider())
        for c in candidates
    ]
    return candidates, entailed


def _report(bank: Bank) -> GapReport:
    candidates, entailed = _stages(bank, REQUIREMENTS)
    return build_report(POSTING, _extraction(REQUIREMENTS), candidates, entailed, bank, PROVENANCE)


def test_a_report_with_a_fabricated_fact_id_is_refused(bank: Bank) -> None:
    candidates, entailed = _stages(bank, REQUIREMENTS)
    forged = entailed[0].model_copy(update={"fact_ids": ["F-9999"]})
    with pytest.raises(ReportRefused, match="F-9999"):
        build_report(
            POSTING,
            _extraction(REQUIREMENTS),
            candidates,
            [forged, *entailed[1:]],
            bank,
            PROVENANCE,
        )


def test_a_report_citing_an_unverified_fact_is_refused(bank: Bank) -> None:
    candidates, entailed = _stages(bank, REQUIREMENTS)
    forged = entailed[0].model_copy(update={"fact_ids": ["F-0003"]})
    with pytest.raises(ReportRefused, match="F-0003"):
        build_report(
            POSTING,
            _extraction(REQUIREMENTS),
            candidates,
            [forged, *entailed[1:]],
            bank,
            PROVENANCE,
        )


def test_support_that_cites_no_fact_is_refused(bank: Bank) -> None:
    candidates, entailed = _stages(bank, REQUIREMENTS)
    forged = entailed[0].model_copy(update={"fact_ids": []})
    with pytest.raises(ReportRefused, match="V9"):
        build_report(
            POSTING,
            _extraction(REQUIREMENTS),
            candidates,
            [forged, *entailed[1:]],
            bank,
            PROVENANCE,
        )


def test_a_finished_report_that_was_altered_is_refused_by_verify_report(bank: Bank) -> None:
    report = _report(bank)
    verify_report(report, bank)
    row = report.rows[0].model_copy(update={"fact_ids": ["F-9999"]})
    altered = report.model_copy(update={"rows": [row, *report.rows[1:]]})
    with pytest.raises(ReportRefused):
        verify_report(altered, bank)


def test_the_gap_list_and_score_match_the_hand_computed_values(bank: Bank) -> None:
    report = _report(bank)
    assert report.status is ReportStatus.COMPLETE
    assert report.incomplete_reasons == []
    assert [row.support for row in report.rows] == [Support.STRONG, Support.PARTIAL, Support.NONE]
    assert report.gaps == ["R-2", "R-3"]
    # (3 * 1.0 + 3 * 0.5 + 1 * 0.0) / (3 + 3 + 1) * 100
    assert report.score is not None
    assert report.score.score == pytest.approx(100 * 4.5 / 7)
    assert (report.score.supported, report.score.total) == (2, 3)
    assert report.score_disclaimer == TRIAGE_DISCLAIMER == "triage only, not a probability"
    assert report.rule_only_ids == []
    assert report.provenance == PROVENANCE


def test_a_row_carries_the_gate_the_citations_and_the_validated_rationale(bank: Bank) -> None:
    first, second, third = _report(bank).rows
    assert first.gate is Gate.YEARS_MET
    assert first.fact_ids == ["F-0001"]
    assert first.rationale == "F-0001 shows Python work."
    assert first.entailment is Entailment.CONFIRMED
    assert second.ceiling is Support.PARTIAL
    assert second.gate is Gate.FAMILIAR_LEVEL
    assert third.entailment is Entailment.NOT_NEEDED
    assert third.fact_ids == []
    assert not third.not_model_checked


def test_an_extraction_failure_gives_an_incomplete_report_with_no_score(bank: Bank) -> None:
    failed = ExtractionResult(
        status=ExtractionStatus.INCOMPLETE,
        requirements=[],
        dropped=[],
        not_assessed_count=0,
        failure="provider_unavailable",
        usage=None,
        prompt_hash="a" * 64,
        schema_version=1,
    )
    report = build_report(POSTING, failed, [], [], bank, PROVENANCE)
    assert report.status is ReportStatus.INCOMPLETE
    assert report.score is None
    assert report.rows == []
    assert report.gaps == []
    assert report.incomplete_reasons == ["extraction failed: provider_unavailable"]


def test_a_failed_entailment_call_keeps_the_score_and_flags_the_requirement(bank: Bank) -> None:
    candidates = retrieve(REQUIREMENTS, bank, LOCAL, TODAY, load_aliases())
    entailed = [
        entail(requirement, candidate, bank, _unreachable_provider())
        for requirement, candidate in zip(REQUIREMENTS, candidates, strict=True)
    ]
    report = build_report(
        POSTING, _extraction(REQUIREMENTS), candidates, entailed, bank, PROVENANCE
    )
    assert report.status is ReportStatus.INCOMPLETE
    assert report.rule_only_ids == ["R-1", "R-2"]
    assert [row.not_model_checked for row in report.rows] == [True, True, False]
    assert report.incomplete_reasons == [
        "entailment did not run for R-1, R-2: the score uses the rule ceiling for them"
    ]
    assert report.score is not None
    assert report.score.score == pytest.approx(100 * 4.5 / 7)
    assert report.rows[0].fact_ids == ["F-0001"]
    assert report.rows[0].rationale is None
    assert report.rows[0].failure == "provider_unavailable"


def test_no_requirements_is_complete_with_no_score(bank: Bank) -> None:
    report = build_report(POSTING, _extraction([]), [], [], bank, PROVENANCE)
    assert report.status is ReportStatus.COMPLETE
    assert report.score is not None
    assert report.score.score is None
    assert report.rows == []


def test_the_recorded_model_output_with_unmatched_terms_is_all_gaps(bank: Bank) -> None:
    recorded = ExtractionOutput.model_validate(
        json.loads((FIXTURES / "recorded_qwen3.5-0.8b.json").read_text(encoding="utf-8"))
    )
    extraction = finish_extraction(
        POSTING_TEXT, recorded, "a" * 64, Usage(input_tokens=1, output_tokens=1)
    )
    candidates = retrieve(extraction.requirements, bank, LOCAL, TODAY, load_aliases())
    entailed = [
        entail(requirement, candidate, bank, _unreachable_provider())
        for requirement, candidate in zip(extraction.requirements, candidates, strict=True)
    ]
    report = build_report(POSTING, extraction, candidates, entailed, bank, PROVENANCE)
    assert report.gaps == ["R-1", "R-2"]
    assert report.score is not None
    assert report.score.score == 0
    assert report.status is ReportStatus.COMPLETE


def test_stage_outputs_that_do_not_line_up_are_an_error(bank: Bank) -> None:
    candidates, entailed = _stages(bank, REQUIREMENTS)
    with pytest.raises(ValueError, match="R-1"):
        build_report(
            POSTING,
            _extraction(REQUIREMENTS),
            candidates,
            [entailed[1], entailed[0], entailed[2]],
            bank,
            PROVENANCE,
        )


def test_the_not_assessed_count_is_carried(bank: Bank) -> None:
    extraction = _extraction([]).model_copy(update={"not_assessed_count": 4})
    report = build_report(POSTING, extraction, [], [], bank, PROVENANCE)
    assert report.not_assessed_count == 4


def test_a_report_survives_a_json_round_trip(bank: Bank) -> None:
    report = _report(bank)
    assert GapReport.model_validate_json(report.model_dump_json()) == report
