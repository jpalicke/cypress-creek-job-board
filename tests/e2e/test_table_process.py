# ABOUTME: Runs the table builder as a real child process over real run files in a temporary folder.
# ABOUTME: Generating twice gives the same bytes, and a hand edited table fails the CI check.
import subprocess
import sys
from pathlib import Path

from table_support import header, publish

from evals.harness.table import README_END, README_START

ROOT = Path(__file__).resolve().parents[2]


def run_table(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.harness.table",
            "--results",
            str(tmp_path / "results"),
            "--backends",
            str(ROOT / "evals" / "backends.yaml"),
            "--page",
            str(tmp_path / "page.md"),
            "--readme",
            str(tmp_path / "README.md"),
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_generate_check_and_catch_a_hand_edit(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        f"# Title\n\n{README_START}\n{README_END}\n", encoding="utf-8"
    )
    publish(tmp_path / "results", header())

    first = run_table(tmp_path)
    assert first.returncode == 0, first.stderr
    page = (tmp_path / "page.md").read_bytes()
    assert b"Ollama qwen3.5:4b" in page and b"not run" in page

    assert run_table(tmp_path).returncode == 0
    assert (tmp_path / "page.md").read_bytes() == page
    assert run_table(tmp_path, "--check").returncode == 0

    (tmp_path / "page.md").write_bytes(page.replace(b"1.000", b"0.999"))
    edited = run_table(tmp_path, "--check")
    assert edited.returncode == 1
    assert "out of date" in edited.stderr
    assert "Traceback" not in edited.stderr


def test_the_committed_table_is_current_when_run_from_the_repository() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "evals.harness.table", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
