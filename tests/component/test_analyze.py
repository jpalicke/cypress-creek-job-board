# ABOUTME: Tests the pipeline run: stage wiring, derived provenance, failures and the budget stop.
# ABOUTME: Stages are real, and the model is a closed port that fails the way an outage does.
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from cypress_creek.config import parse_settings
from cypress_creek.eval_records import CallRecord
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
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
from cypress_creek.pipeline.entail import Entailment
from cypress_creek.pipeline.extract import (
    ExtractionResult,
    ExtractionStatus,
    extract_requirements,
    finish_extraction,
)
from cypress_creek.pipeline.report import ReportStatus
from cypress_creek.pipeline.run import analyze, assess, run_id
from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import (
    Budget,
    BudgetedProvider,
    BudgetExceeded,
    BudgetTracker,
    OllamaProvider,
)
from cypress_creek.providers.base import CostPerMtok, Usage
from cypress_creek.scoring.support import Support

FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"
TODAY = date(2024, 6, 1)
# Nothing listens on the discard port. A call that reached the network is ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"
BACKEND = "ollama"
MODEL = "qwen3.5:0.8b"

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
EXTRACTION_USAGE = Usage(input_tokens=500, output_tokens=60)


def _requirement(n: int, term: str, importance: Importance) -> Requirement:
    return Requirement(
        id=f"R-{n}",
        text=f"Needs {term}.",
        span=(0, 10),
        kind=RequirementKind.SKILL,
        term=term,
        importance=importance,
    )


def _extraction(requirements: list[Requirement]) -> ExtractionResult:
    return ExtractionResult(
        status=ExtractionStatus.OK,
        requirements=requirements,
        dropped=[],
        not_assessed_count=0,
        failure=None,
        usage=EXTRACTION_USAGE,
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
        parse_settings({"provider": BACKEND, "model": MODEL, "base_url": NOTHING_LISTENING})
    )


def _no_sleep(_seconds: float) -> None:
    return None


def test_assess_runs_retrieval_entailment_and_the_report_over_an_extraction(bank: Bank) -> None:
    extraction = _extraction(
        [
            _requirement(1, "python", Importance.REQUIRED),
            _requirement(2, "kubernetes", Importance.PREFERRED),
        ]
    )
    report = assess(
        POSTING,
        extraction,
        bank,
        _unreachable_provider(),
        backend=BACKEND,
        model=MODEL,
        today=TODAY,
        sleep=_no_sleep,
    )
    by_id = {row.requirement_id: row for row in report.rows}
    assert by_id["R-1"].entailment is Entailment.NOT_RUN
    assert by_id["R-1"].support is Support.STRONG
    assert by_id["R-1"].fact_ids == ["F-0001"]
    assert by_id["R-2"].entailment is Entailment.NOT_NEEDED
    assert by_id["R-2"].support is Support.NONE
    assert report.gaps == ["R-2"]
    assert report.status is ReportStatus.INCOMPLETE
    assert report.rule_only_ids == ["R-1"]
    assert report.score is not None
    assert report.score.score == pytest.approx(100 * 3 / 4)


def test_provenance_is_derived_from_the_inputs_and_the_stage_outputs(bank: Bank) -> None:
    extraction = _extraction([_requirement(1, "python", Importance.REQUIRED)])
    report = assess(
        POSTING,
        extraction,
        bank,
        _unreachable_provider(),
        backend=BACKEND,
        model=MODEL,
        today=TODAY,
        sleep=_no_sleep,
    )
    provenance = report.provenance
    assert provenance.backend == BACKEND
    assert provenance.model == MODEL
    assert provenance.run_id == run_id(POSTING.text_hash, bank_hash(bank), BACKEND, MODEL)
    assert provenance.prompt_hashes["extract"] == "a" * 64
    assert len(provenance.prompt_hashes["entail"]) == 64
    assert provenance.usage == EXTRACTION_USAGE


def test_a_run_with_no_entailment_call_records_no_entailment_prompt_hash(bank: Bank) -> None:
    extraction = _extraction([_requirement(1, "kubernetes", Importance.REQUIRED)])
    report = assess(
        POSTING,
        extraction,
        bank,
        _unreachable_provider(),
        backend=BACKEND,
        model=MODEL,
        today=TODAY,
        sleep=_no_sleep,
    )
    assert report.status is ReportStatus.COMPLETE
    assert list(report.provenance.prompt_hashes) == ["extract"]


def test_the_run_id_changes_when_the_bank_changes(bank: Bank, tmp_path: Path) -> None:
    extraction = _extraction([_requirement(1, "kubernetes", Importance.REQUIRED)])
    smaller = Bank(facts=bank.facts[:1])
    ids = {
        assess(
            POSTING,
            extraction,
            facts,
            _unreachable_provider(),
            backend=BACKEND,
            model=MODEL,
            today=TODAY,
            sleep=_no_sleep,
        ).provenance.run_id
        for facts in (bank, bank, smaller)
    }
    assert len(ids) == 2


def test_the_recorded_model_output_runs_through_to_a_complete_report(bank: Bank) -> None:
    recorded = ExtractionOutput.model_validate(
        json.loads((FIXTURES / "recorded_qwen3.5-0.8b.json").read_text(encoding="utf-8"))
    )
    extraction = finish_extraction(POSTING_TEXT, recorded, "a" * 64, EXTRACTION_USAGE)
    report = assess(
        POSTING,
        extraction,
        bank,
        _unreachable_provider(),
        backend=BACKEND,
        model=MODEL,
        today=TODAY,
        sleep=_no_sleep,
    )
    assert report.status is ReportStatus.COMPLETE
    assert report.score is not None
    assert report.score.score == 0


def test_a_failed_extraction_call_gives_an_incomplete_report_not_a_crash(bank: Bank) -> None:
    report = analyze(
        POSTING,
        bank,
        _unreachable_provider(),
        backend=BACKEND,
        model=MODEL,
        today=TODAY,
        sleep=_no_sleep,
    )
    assert report.status is ReportStatus.INCOMPLETE
    assert report.rows == []
    assert report.score is None
    assert report.incomplete_reasons == ["extraction failed: provider_unavailable"]
    assert report.provenance.run_id == run_id(POSTING.text_hash, bank_hash(bank), BACKEND, MODEL)
    assert list(report.provenance.prompt_hashes) == ["extract"]
    assert report.provenance.usage == Usage(input_tokens=0, output_tokens=0)


def test_a_spent_budget_stops_the_run_instead_of_giving_a_report(bank: Bank) -> None:
    inner = _unreachable_provider()
    tracker = BudgetTracker(Budget(max_input_tokens=1), inner.capabilities.cost_per_mtok)
    with pytest.raises(BudgetExceeded):
        analyze(
            POSTING,
            bank,
            BudgetedProvider(inner, tracker),
            backend=BACKEND,
            model=MODEL,
            today=TODAY,
            sleep=_no_sleep,
        )


def test_extraction_trace_keeps_unknown_usage_for_a_failed_attempt() -> None:
    trace = PipelineTrace()
    result = extract_requirements(POSTING_TEXT, _unreachable_provider(), trace=trace)

    assert result.status is ExtractionStatus.INCOMPLETE
    assert len(trace.calls) == 1
    call = trace.calls[0]
    assert isinstance(call, CallRecord)
    assert call.stage == "extract"
    assert call.prompt_hash == result.prompt_hash
    assert call.schema_version == result.schema_version
    assert call.outcome == "error"
    assert call.error_type == "ProviderUnavailable"
    assert call.usage is None
    assert call.cost_usd is None
    assert trace.validators == []


def test_extraction_trace_has_no_call_for_a_budget_refusal() -> None:
    inner = _unreachable_provider()
    tracker = BudgetTracker(Budget(max_input_tokens=1), inner.capabilities.cost_per_mtok)
    trace = PipelineTrace()
    with pytest.raises(BudgetExceeded):
        extract_requirements(POSTING_TEXT, BudgetedProvider(inner, tracker), trace=trace)
    assert trace.calls == []


def test_analyze_passes_one_trace_from_extraction_through_report(bank: Bank) -> None:
    trace = PipelineTrace()
    report = analyze(
        POSTING,
        bank,
        _unreachable_provider(),
        backend=BACKEND,
        model=MODEL,
        today=TODAY,
        sleep=_no_sleep,
        trace=trace,
    )

    assert report.status is ReportStatus.INCOMPLETE
    assert [call.stage for call in trace.calls] == ["extract"]
    assert [(item.stage, item.verdict.validator) for item in trace.validators] == [
        ("report", "V4"),
        ("report", "V5"),
        ("report", "V9"),
    ]


def test_assess_passes_trace_through_entailment_and_report(bank: Bank) -> None:
    trace = PipelineTrace()
    extraction = _extraction([_requirement(1, "python", Importance.REQUIRED)])
    report = assess(
        POSTING,
        extraction,
        bank,
        _unreachable_provider(),
        backend=BACKEND,
        model=MODEL,
        today=TODAY,
        sleep=_no_sleep,
        trace=trace,
    )

    assert report.status is ReportStatus.INCOMPLETE
    assert [call.stage for call in trace.calls] == ["entail"]
    assert [item.verdict.validator for item in trace.validators] == ["V13", "V4", "V5", "V9"]
    assert trace.validators[0].stage == "extract"
    assert trace.validators[0].subject == POSTING.id
    assert trace.validators[0].verdict.passed is False
    assert trace.validators[0].verdict.offending == "You must have 3 years of Python experience."
    assert all(item.stage == "report" for item in trace.validators[1:])


def test_trace_cost_and_call_record_require_observed_usage() -> None:
    trace = PipelineTrace()
    trace.record_call(
        stage="extract",
        prompt_hash="a" * 64,
        schema_version=1,
        usage=Usage(input_tokens=1_000, output_tokens=500),
        cost_per_mtok=CostPerMtok(input=2, output=4),
    )
    assert trace.calls[0].cost_usd == pytest.approx(0.004)
    assert trace.calls[0].outcome == "success"
    assert trace.calls[0].error_type is None
    with pytest.raises(ValidationError):
        CallRecord(
            stage="extract",
            prompt_hash="a" * 64,
            schema_version=1,
            outcome="error",
            error_type="ProviderUnavailable",
            usage=None,
            cost_usd=0,
        )
