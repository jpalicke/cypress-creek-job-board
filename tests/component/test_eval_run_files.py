# ABOUTME: Exercises SQLite eval runs and JSONL exports on real local files.
# ABOUTME: Failed runs retain completed pairs while invalid records cannot advance state.
import json
import sqlite3
from pathlib import Path

import pytest

from cypress_creek.eval_records import (
    CallRecord,
    CaseRecord,
    RunHeader,
    RunTerminal,
    ValidatorRecord,
    load_run,
    parse_run_rows,
)
from cypress_creek.eval_store import EvalStore
from cypress_creek.pipeline.report import GapReport, Provenance, ReportStatus
from cypress_creek.providers.base import Usage
from cypress_creek.storage.db import connect, migrate
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


@pytest.mark.parametrize("missing", ["calls", "validators", "report"])
def test_case_row_missing_audit_data_is_rejected(missing: str) -> None:
    header = _header()
    row = _case(header, 1).model_dump(mode="json")
    del row[missing]
    with pytest.raises(ValueError):
        parse_run_rows([header.model_dump_json(), json.dumps(row)])


def test_malformed_jsonl_tail_is_not_silently_treated_as_a_complete_pair(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    path.write_text(_header().model_dump_json() + '\n{"record_type":"case"', encoding="utf-8")
    with pytest.raises(ValueError):
        load_run(path)


def test_sqlite_eval_run_resumes_completed_pairs_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    header = _header()
    conn = connect(path)
    migrate(conn)
    store = EvalStore(conn)
    store.start(header)
    store.append_case(header, _case(header, 1))
    store.append_terminal(
        header, RunTerminal(run_id=header.run_id, status="failed", reason="provider_unavailable")
    )
    conn.close()

    conn = connect(path)
    store = EvalStore(conn)
    failed = store.load(header)
    assert failed.status == "failed"
    assert failed.pending_pairs == {("case-1", 2)}
    assert failed.cases == (_case(header, 1),)
    store.append_case(header, _case(header, 2))
    store.append_terminal(header, RunTerminal(run_id=header.run_id, status="complete"))
    assert store.load(header).status == "complete"
    assert conn.execute("SELECT COUNT(*) FROM eval_event").fetchone() == (4,)
    conn.close()


def test_sqlite_eval_run_rejects_invalid_append_without_losing_rows(tmp_path: Path) -> None:
    conn = connect(tmp_path / "runs.sqlite3")
    migrate(conn)
    header = _header()
    store = EvalStore(conn)
    store.start(header)
    first = _case(header, 1)
    store.append_case(header, first)

    with pytest.raises(ValueError, match="duplicate"):
        store.append_case(header, first)
    with pytest.raises(ValueError, match="missing case"):
        store.append_terminal(header, RunTerminal(run_id=header.run_id, status="complete"))

    assert store.load(header).cases == (first,)
    assert conn.execute("SELECT COUNT(*) FROM eval_event").fetchone() == (1,)
    conn.close()


def test_sqlite_rejects_torn_record_without_losing_completed_pair(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    conn = connect(path)
    migrate(conn)
    header = _header()
    store = EvalStore(conn)
    store.start(header)
    first = _case(header, 1)
    store.append_case(header, first)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO eval_event (run_id, record_json) VALUES (?, ?)",
            (header.run_id, '{"record_type":"case"'),
        )
    conn.close()

    conn = connect(path)
    assert EvalStore(conn).load(header).cases == (first,)
    conn.close()


def test_sqlite_export_round_trips_history_without_overwriting(tmp_path: Path) -> None:
    conn = connect(tmp_path / "runs.sqlite3")
    migrate(conn)
    header = _header()
    store = EvalStore(conn)
    store.start(header)
    store.append_case(header, _case(header, 1))
    store.append_terminal(
        header, RunTerminal(run_id=header.run_id, status="failed", reason="provider_unavailable")
    )
    store.append_case(header, _case(header, 2))
    store.append_terminal(header, RunTerminal(run_id=header.run_id, status="complete"))
    path = tmp_path / "run.jsonl"

    store.export_jsonl(header, path)

    assert load_run(path, expected_header=header) == store.load(header)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 5
    with pytest.raises(FileExistsError):
        store.export_jsonl(header, path)
    assert store.load(header).status == "complete"
    conn.close()


def test_sqlite_export_rejects_damaged_stored_row_without_writing(tmp_path: Path) -> None:
    conn = connect(tmp_path / "runs.sqlite3")
    migrate(conn)
    header = _header()
    store = EvalStore(conn)
    store.start(header)
    conn.execute(
        "INSERT INTO eval_event (run_id, record_json) VALUES (?, ?)",
        (header.run_id, '{"record_type":"case","run_id":"' + header.run_id + '"}'),
    )
    path = tmp_path / "run.jsonl"

    with pytest.raises(ValueError):
        store.export_jsonl(header, path)

    assert not path.exists()
    conn.close()
