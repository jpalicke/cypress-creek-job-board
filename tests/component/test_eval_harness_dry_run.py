# ABOUTME: Runs the eval CLI dry path with a real Ollama adapter pointed at a closed port.
# ABOUTME: A dry run reports exact initial extraction calls and bounded model-dependent work.
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dry_run_reports_the_call_plan_without_network_or_database(tmp_path: Path) -> None:
    manifest = tmp_path / "cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "technical-smoke",
                        "posting": "Needs Python and PostgreSQL.",
                        "as_of": "2024-06-01",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    database = tmp_path / "eval.sqlite3"
    environment = os.environ.copy()
    environment["CYPRESS_CREEK_BASE_URL"] = "http://127.0.0.1:9"
    environment["CYPRESS_CREEK_CONTEXT_TOKENS"] = "4096"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.run",
            "--backend",
            "ollama",
            "--model",
            "qwen3.5:0.8b",
            "--cases",
            str(manifest),
            "--repeats",
            "2",
            "--out",
            str(database),
            "--dry-run",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    plan = json.loads(result.stdout)
    assert plan["planned_pairs"] == 2
    assert plan["extraction_initial_calls_exact"] == 2
    assert plan["entailment_initial_calls_upper_bound"] == 80
    assert plan["provider_attempts_upper_bound"] == 410
    assert plan["cost_usd_upper_bound"] == 0
    assert not database.exists()

    export = ROOT / "evals" / "scratch" / "dry-run.jsonl"
    with_export = subprocess.run(
        [*result.args, "--export", str(export)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert with_export.returncode != 0
    assert "--export requires a live run" in with_export.stderr
    assert not export.exists()
