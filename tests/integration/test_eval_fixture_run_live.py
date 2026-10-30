# ABOUTME: Runs one committed fixture through the eval CLI with a real Ollama model, then scores it.
# ABOUTME: Proves a CLI run is scorable: the fixture ids join the labels and the labels are frozen.
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from cypress_creek.eval_records import load_run
from evals.harness.fixtures import discover_fixtures

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "evals" / "fixtures"
SCRATCH = ROOT / "evals" / "scratch"
MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", "http://localhost:11434")


@pytest.fixture
def scratch_dir() -> Iterator[Path]:
    SCRATCH.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SCRATCH) as name:
        yield Path(name)


def test_a_fixture_run_can_be_scored_by_the_scorer(scratch_dir: Path) -> None:
    name = discover_fixtures(FIXTURES)[0].name
    export = scratch_dir / "run.jsonl"
    environment = {
        **os.environ,
        "CYPRESS_CREEK_BASE_URL": BASE_URL,
        "CYPRESS_CREEK_CONTEXT_TOKENS": "16384",
        # A slow shared runner can take minutes for one call of a small model on a real posting.
        "CYPRESS_CREEK_REQUEST_TIMEOUT_SECONDS": "900",
    }

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.run",
            "--backend",
            "ollama",
            "--model",
            MODEL,
            "--fixtures",
            "--only",
            name,
            "--repeats",
            "1",
            "--out",
            str(scratch_dir / "eval.sqlite3"),
            "--export",
            str(export),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=1500,
        check=False,
    )

    assert run.returncode == 0, run.stderr + run.stdout
    state = load_run(export)
    assert state.header.case_ids == [name]
    assert state.status == "complete"

    scored = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.score",
            "--run",
            str(export),
            "--out",
            str(scratch_dir / "metrics"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=ROOT,
    )

    assert scored.returncode == 0, scored.stderr
    assert name not in scored.stderr
    assert "ollama" in scored.stdout
