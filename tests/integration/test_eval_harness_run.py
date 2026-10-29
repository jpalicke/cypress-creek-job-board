# ABOUTME: Exercises the eval CLI against SQLite with a real Ollama adapter.
# ABOUTME: Provider failures retain pending cases and count attempted calls across resumes.
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from cypress_creek.eval_records import RunHeader, RunTerminal, load_run, parse_run_rows
from cypress_creek.eval_store import EvalStore
from cypress_creek.pipeline.trace import CallRecord
from cypress_creek.storage.db import connect

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "evals" / "cases" / "technical-smoke.json"
MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
LIVE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", "http://localhost:11434")
SCRATCH = ROOT / "evals" / "scratch"


@pytest.fixture
def scratch_dir() -> Iterator[Path]:
    SCRATCH.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SCRATCH) as name:
        yield Path(name)


def test_failed_terminals_preserve_attempts_across_resumes() -> None:
    digest = "a" * 64
    header = RunHeader(
        git_commit="b" * 40,
        backend="ollama",
        model=MODEL,
        prompt_hashes={"extract": digest},
        schema_versions={"extract": 1},
        fixture_set_hash=digest,
        bank_hash=digest,
        case_ids=["one"],
        repeats=1,
    )
    attempt = CallRecord(
        stage="extract",
        prompt_hash=digest,
        schema_version=1,
        outcome="error",
        error_type="ProviderUnavailable",
        usage=None,
        cost_usd=None,
    )
    terminal = RunTerminal(
        run_id=header.run_id, status="failed", reason="provider_unavailable", calls=[attempt]
    )

    state = parse_run_rows(
        [header.model_dump_json(), terminal.model_dump_json(), terminal.model_dump_json()]
    )

    assert state.pending_pairs == {("one", 1)}
    assert state.failed_calls == (attempt, attempt)


def _run(
    database: Path,
    base_url: str,
    *,
    max_requests: int | None = None,
    export: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CYPRESS_CREEK_BASE_URL"] = base_url
    environment["CYPRESS_CREEK_CONTEXT_TOKENS"] = "4096"
    if max_requests is not None:
        environment["CYPRESS_CREEK_MAX_REQUESTS"] = str(max_requests)
    command = [
        sys.executable,
        "-m",
        "evals.harness.run",
        "--backend",
        "ollama",
        "--model",
        MODEL,
        "--cases",
        str(SMOKE),
        "--repeats",
        "1",
        "--out",
        str(database),
    ]
    if export is not None:
        command.extend(["--export", str(export)])
    return subprocess.run(
        command,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _stored(database: Path) -> tuple[RunHeader, EvalStore, sqlite3.Connection]:
    connection = connect(database)
    (header_json,) = connection.execute("SELECT header_json FROM eval_run").fetchone()
    header = RunHeader.model_validate_json(header_json)
    return header, EvalStore(connection), connection


@pytest.mark.live
def test_live_run_persists_report_trace_and_complete_terminal(
    tmp_path: Path, scratch_dir: Path
) -> None:
    database = tmp_path / "runs.sqlite3"
    export = scratch_dir / "technical-smoke.jsonl"

    result = _run(database, LIVE_URL, export=export)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    header, store, connection = _stored(database)
    state = store.load(header)
    assert state.status == "complete"
    assert state.pending_pairs == set()
    assert len(state.cases) == 1
    assert state.cases[0].case_id == "technical-smoke"
    assert state.cases[0].calls
    assert any(call.usage is not None for call in state.cases[0].calls)
    assert [item.verdict.validator for item in state.cases[0].validators[-3:]] == [
        "V4",
        "V5",
        "V9",
    ]
    assert load_run(export, expected_header=header) == state
    connection.close()


def test_export_outside_scratch_is_rejected_before_provider_work(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    export = tmp_path / "audit.jsonl"

    result = _run(database, "http://127.0.0.1:9", export=export)

    assert result.returncode != 0
    assert "evals/scratch" in result.stderr.replace("\\", "/")
    assert not database.exists()
    assert not export.exists()


def test_existing_export_is_not_overwritten_or_charged(tmp_path: Path, scratch_dir: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    export = scratch_dir / "existing.jsonl"
    export.write_text("keep me", encoding="utf-8")

    result = _run(database, "http://127.0.0.1:9", export=export)

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert export.read_text(encoding="utf-8") == "keep me"
    assert not database.exists()


def test_failed_run_exports_its_terminal(tmp_path: Path, scratch_dir: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    export = scratch_dir / "failed.jsonl"

    result = _run(database, "http://127.0.0.1:9", export=export)

    assert result.returncode != 0
    assert result.stderr == ""
    header, store, connection = _stored(database)
    assert load_run(export, expected_header=header) == store.load(header)
    assert store.load(header).status == "failed"
    connection.close()


def test_unreachable_backend_records_failure_and_replays_its_attempt_budget(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    unreachable = "http://127.0.0.1:9"

    first = _run(database, unreachable, max_requests=1)

    assert first.returncode != 0
    assert first.stderr == ""
    header, store, connection = _stored(database)
    failed = store.load(header)
    assert failed.status == "failed"
    assert failed.pending_pairs == {("technical-smoke", 1)}
    assert failed.cases == ()
    assert len(failed.failed_calls) == 1
    assert failed.failed_calls[0].error_type == "ProviderUnavailable"
    assert failed.failed_calls[0].usage is None
    connection.close()

    second = _run(database, unreachable, max_requests=1)

    assert second.returncode != 0
    assert second.stderr == ""
    assert json.loads(second.stdout)["reason"] == "budget_exceeded"
    header, store, connection = _stored(database)
    resumed = store.load(header)
    assert resumed.pending_pairs == {("technical-smoke", 1)}
    assert len(resumed.failed_calls) == 1
    connection.close()
