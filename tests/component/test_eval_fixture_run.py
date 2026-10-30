# ABOUTME: Runs the eval CLI over the committed labeled fixtures with an adapter on a closed port.
# ABOUTME: A dry run plans every fixture, and labels that are not committed refuse before any work.
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from evals.harness.fixtures import discover_fixtures

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "evals" / "fixtures"
COUNT = len(discover_fixtures(FIXTURES))


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CYPRESS_CREEK_BASE_URL"] = "http://127.0.0.1:9"
    environment["CYPRESS_CREEK_CONTEXT_TOKENS"] = "4096"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.run",
            "--backend",
            "ollama",
            "--model",
            "qwen3.5:0.8b",
            "--repeats",
            "2",
            *arguments,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_a_dry_run_plans_every_committed_fixture() -> None:
    result = _run("--fixtures", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    plan = json.loads(result.stdout)
    assert plan["planned_pairs"] == COUNT * 2
    assert plan["extraction_initial_calls_exact"] == COUNT * 2


def test_only_narrows_the_plan_to_the_named_fixtures() -> None:
    name = discover_fixtures(FIXTURES)[0].name

    result = _run("--fixtures", "--only", name, "--dry-run")

    assert json.loads(result.stdout)["planned_pairs"] == 2


def test_an_unknown_fixture_id_is_refused_without_a_traceback() -> None:
    result = _run("--fixtures", "--only", "nope", "--dry-run")

    assert result.returncode == 1
    assert "no fixture named nope" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_labels_that_are_not_committed_refuse_before_any_work(tmp_path: Path) -> None:
    loose = tmp_path / "fixtures"
    shutil.copytree(discover_fixtures(FIXTURES)[0], loose / discover_fixtures(FIXTURES)[0].name)

    result = _run("--fixtures", str(loose), "--dry-run")

    assert result.returncode == 1
    assert "labels.yaml is not tracked by git" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_cases_and_fixtures_are_exclusive_and_one_is_required() -> None:
    both = _run("--fixtures", "--cases", "x.json", "--dry-run")
    neither = _run("--dry-run")

    assert both.returncode == 2 and neither.returncode == 2
