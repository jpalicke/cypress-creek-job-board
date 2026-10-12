# ABOUTME: Exercises eval JSONL files on disk through interrupted and resumed runs.
# ABOUTME: A failed terminal stays visible while completed case pairs remain reusable.
import json
from pathlib import Path

import pytest

from cypress_creek.eval_records import (
    CallRecord,
    CaseRecord,
    RunHeader,
    RunTerminal,
    ValidatorRecord,
    append_case,
    append_terminal,
    load_run,
    write_header,
)
from cypress_creek.pipeline.report import GapReport, Provenance, ReportStatus
from cypress_creek.providers.base import Usage
from cypress_creek.validators.verdict import Verdict


def _header(**changes: object) -> RunHeader:
    fields: dict[str, object] = {
        "git_commit": "a" * 40,
        "backend": "ollama",
        "model": "qwen3.5:0.8b",
        "prompt_hashes": {"extract": "b" * 64},
        "schema_versions": {"extract": 1},
        "fixture_set_hash": "c" * 64,
        "bank_hash": "d" * 64,
        "case_ids": ["case-1"],
        "repeats": 2,
    }
    fields.update(changes)
    return RunHeader.model_validate(fields)


def _case(header: RunHeader, repeat: int) -> CaseRecord:
    report = GapReport(
        posting_id="posting-1",
        status=ReportStatus.INCOMPLETE,
        incomplete_reasons=["extraction failed: schema_violation"],
        rows=[],
        gaps=[],
        not_assessed_count=0,
        dropped=[],
        warnings=[],
        score=None,
        score_disclaimer="triage only, not a probability",
        rule_only_ids=[],
        provenance=Provenance(
            backend=header.backend,
            model=header.model,
            run_id="pipeline-run-id",
            prompt_hashes=header.prompt_hashes,
            usage=Usage(input_tokens=21, output_tokens=4),
        ),
    )
    return CaseRecord(
        run_id=header.run_id,
        case_id="case-1",
        repeat=repeat,
        posting_hash="e" * 64,
        report=report,
        calls=[
            CallRecord(
                stage="extract",
                prompt_hash=header.prompt_hashes["extract"],
                schema_version=1,
                usage=Usage(input_tokens=21, output_tokens=4),
                cost_usd=0,
            )
        ],
        validators=[
            ValidatorRecord(
                stage="extract", subject="R-1", verdict=Verdict(validator="V1", passed=True)
            )
        ],
    )


def test_failed_run_resumes_only_missing_case_pairs(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    header = _header()
    write_header(path, header)
    append_case(path, header, _case(header, 1))
    append_terminal(
        path,
        header,
        RunTerminal(run_id=header.run_id, status="failed", reason="provider_unavailable"),
    )

    failed = load_run(path, expected_header=header)
    assert failed.status == "failed"
    assert failed.pending_pairs == {("case-1", 2)}
    assert failed.cases == (_case(header, 1),)

    append_case(path, header, _case(header, 2))
    append_terminal(path, header, RunTerminal(run_id=header.run_id, status="complete"))
    resumed = load_run(path, expected_header=header)
    assert resumed.status == "complete"
    assert resumed.pending_pairs == set()
    assert len(resumed.cases) == 2
    assert len(path.read_text(encoding="utf-8").splitlines()) == 5


def test_mismatched_identity_and_duplicate_case_cannot_be_appended(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    header = _header()
    write_header(path, header)
    with pytest.raises(ValueError, match="identity"):
        load_run(path, expected_header=_header(prompt_hashes={"extract": "f" * 64}))
    first = _case(header, 1)
    append_case(path, header, first)
    with pytest.raises(ValueError, match="duplicate"):
        append_case(path, header, first)
    with pytest.raises(ValueError, match="missing case"):
        append_terminal(path, header, RunTerminal(run_id=header.run_id, status="complete"))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.parametrize("missing", ["calls", "validators", "report"])
def test_case_row_missing_audit_data_is_rejected(tmp_path: Path, missing: str) -> None:
    path = tmp_path / "run.jsonl"
    header = _header()
    write_header(path, header)
    row = _case(header, 1).model_dump(mode="json")
    del row[missing]
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(row) + "\n")
    with pytest.raises(ValueError):
        load_run(path)


def test_malformed_jsonl_tail_is_not_silently_treated_as_a_complete_pair(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    write_header(path, _header())
    with path.open("a", encoding="utf-8") as output:
        output.write('{"record_type":"case"')
    with pytest.raises(ValueError):
        load_run(path)
