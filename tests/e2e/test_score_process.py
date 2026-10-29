# ABOUTME: Runs the score CLI as a separate process on a run file built from real fixture labels.
# ABOUTME: Checks the printed summary and mismatch view, the metrics file and the exit codes.
import json
import subprocess
import sys
from pathlib import Path

from eval_support import case_record, header_for, mirror_report, write_run

from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from evals.harness.fixtures import discover_fixtures, load_fixture

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = load_fixture(discover_fixtures(ROOT / "evals" / "fixtures")[0])
CASE_ID = FIXTURE.meta.fixture_id
BANK = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)


def _run_file(tmp_path: Path, digest: str) -> Path:
    header = header_for([CASE_ID], 1, digest)
    skipped = FIXTURE.labels.requirements[0].id
    report = mirror_report(FIXTURE.labels, FIXTURE.text, skip=frozenset({skipped}))
    path = tmp_path / "run.jsonl"
    write_run(path, header, [case_record(header, CASE_ID, 1, FIXTURE.text, report)], complete=True)
    return path


def _score(path: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.score",
            "--run",
            str(path),
            "--out",
            str(out),
            "--diff",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=ROOT,
    )


def test_a_separate_process_scores_a_run_and_shows_the_mismatch(tmp_path: Path) -> None:
    result = _score(_run_file(tmp_path, bank_hash(BANK)), tmp_path / "out")

    assert result.returncode == 0, result.stderr
    assert "ollama qwen3.5:0.8b" in result.stdout
    assert f"{CASE_ID} repeat 1 {FIXTURE.labels.requirements[0].id}: not extracted" in result.stdout
    (written,) = list((tmp_path / "out").iterdir())
    metrics = json.loads(written.read_text(encoding="utf-8"))
    recall = metrics["metrics"]["requirement_recall"]
    expected = (len(FIXTURE.labels.requirements) - 1) / len(FIXTURE.labels.requirements)
    assert recall["mean"] == expected
    assert metrics["run_status"] == "complete"


def test_a_run_made_with_another_bank_exits_one_with_a_message(tmp_path: Path) -> None:
    result = _score(_run_file(tmp_path, "f" * 64), tmp_path / "out")

    assert result.returncode == 1
    assert "different bank" in result.stderr
    assert not (tmp_path / "out").exists()
