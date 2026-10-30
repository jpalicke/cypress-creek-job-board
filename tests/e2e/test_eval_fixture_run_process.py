# ABOUTME: Runs the eval CLI in a child process over a fixture with the backend unreachable.
# ABOUTME: The failure is loud, and the export header carries the fixture ids and set hash.
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from cypress_creek.eval_records import RunHeader
from evals.harness.fixtures import discover_fixtures, load_fixture
from evals.harness.fixtures import fixture_set_hash as labeled_set_hash

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "evals" / "fixtures"
SCRATCH = ROOT / "evals" / "scratch"


@pytest.fixture
def scratch_dir() -> Iterator[Path]:
    SCRATCH.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SCRATCH) as name:
        yield Path(name)


def test_an_unreachable_backend_fails_loudly_and_the_header_names_the_fixtures(
    scratch_dir: Path,
) -> None:
    directory = discover_fixtures(FIXTURES)[0]
    export = scratch_dir / "run.jsonl"
    environment = os.environ.copy()
    environment["CYPRESS_CREEK_BASE_URL"] = "http://127.0.0.1:9"
    environment["CYPRESS_CREEK_CONTEXT_TOKENS"] = "32768"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.run",
            "--backend",
            "ollama",
            "--model",
            "qwen3.5:0.8b",
            "--fixtures",
            "--only",
            directory.name,
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
        timeout=120,
        check=False,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"] == "provider_unavailable"
    header = RunHeader.model_validate_json(export.read_text(encoding="utf-8").splitlines()[0])
    assert header.case_ids == [directory.name]
    assert header.fixture_set_hash == labeled_set_hash([load_fixture(directory)])
