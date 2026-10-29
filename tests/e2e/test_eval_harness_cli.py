# ABOUTME: Runs the eval CLI in a separate process against a partly completed real-model run.
# ABOUTME: Resume executes only pending pairs and leaves completed SQLite records unchanged.
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cypress_creek.config import parse_settings
from cypress_creek.eval_records import CaseRecord, RunHeader
from cypress_creek.eval_store import EvalStore
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.pipeline.entail import SCHEMA_VERSION as ENTAIL_SCHEMA_VERSION
from cypress_creek.pipeline.extract import SCHEMA_VERSION as EXTRACT_SCHEMA_VERSION
from cypress_creek.pipeline.prompt import Stage, build_prompt
from cypress_creek.pipeline.run import analyze
from cypress_creek.pipeline.schemas import EntailmentOutput, ExtractionOutput
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.storage.db import connect, migrate
from evals.harness.run import fixture_set_hash, load_cases

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)


def test_cli_resumes_only_the_pending_case_and_then_stays_complete(tmp_path: Path) -> None:
    manifest = tmp_path / "cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {"id": "first", "posting": "Needs Python.", "as_of": "2024-06-01"},
                    {"id": "second", "posting": "Needs PostgreSQL.", "as_of": "2024-06-01"},
                ]
            }
        ),
        encoding="utf-8",
    )
    cases = load_cases(manifest)
    bank = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
    provider = OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 4096}
        )
    )
    capabilities = provider.capabilities
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    header = RunHeader(
        git_commit=git_commit,
        backend="ollama",
        model=MODEL,
        prompt_hashes={
            "extract": build_prompt(
                Stage.EXTRACT, "", [], capabilities, ExtractionOutput
            ).prompt_hash,
            "entail": build_prompt(
                Stage.ENTAIL, "", [], capabilities, EntailmentOutput
            ).prompt_hash,
        },
        schema_versions={"extract": EXTRACT_SCHEMA_VERSION, "entail": ENTAIL_SCHEMA_VERSION},
        fixture_set_hash=fixture_set_hash(cases),
        bank_hash=bank_hash(bank),
        case_ids=[case.id for case in cases],
        repeats=1,
    )
    trace = PipelineTrace()
    first_report = analyze(
        cases[0].posting,
        bank,
        provider,
        backend="ollama",
        model=MODEL,
        today=cases[0].posting.created_at.date(),
        trace=trace,
    )
    first = CaseRecord(
        run_id=header.run_id,
        case_id="first",
        repeat=1,
        posting_hash=cases[0].posting.text_hash,
        report=first_report,
        calls=trace.calls,
        validators=trace.validators,
    )
    database = tmp_path / "runs.sqlite3"
    connection = connect(database)
    migrate(connection)
    store = EvalStore(connection)
    store.start(header)
    store.append_case(header, first)
    connection.close()

    environment = os.environ.copy()
    environment["CYPRESS_CREEK_BASE_URL"] = BASE_URL
    environment["CYPRESS_CREEK_CONTEXT_TOKENS"] = "4096"
    command = [
        sys.executable,
        "-m",
        "evals.harness.run",
        "--backend",
        "ollama",
        "--model",
        MODEL,
        "--cases",
        str(manifest),
        "--repeats",
        "1",
        "--out",
        str(database),
    ]

    second = subprocess.run(
        command, env=environment, capture_output=True, text=True, timeout=180, check=False
    )

    assert second.returncode == 0, second.stderr
    assert second.stderr == ""
    connection = connect(database)
    store = EvalStore(connection)
    completed = store.load(header)
    assert completed.status == "complete"
    assert len(completed.cases) == 2
    assert completed.cases[0] == first
    assert completed.cases[1].case_id == "second"
    event_count = connection.execute("SELECT COUNT(*) FROM eval_event").fetchone()
    connection.close()

    third = subprocess.run(
        command, env=environment, capture_output=True, text=True, timeout=30, check=False
    )

    assert third.returncode == 0, third.stderr
    connection = connect(database)
    assert connection.execute("SELECT COUNT(*) FROM eval_event").fetchone() == event_count
    connection.close()
