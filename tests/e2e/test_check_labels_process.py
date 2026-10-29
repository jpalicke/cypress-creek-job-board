# ABOUTME: Runs the label check as a real child process on the committed fixtures and a bad one.
# ABOUTME: A bad span or fact reference must exit nonzero and name the problem on standard error.
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
FIXTURES = ROOT / "evals" / "fixtures"


def run_check(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "evals.harness.check_labels", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_committed_fixtures_pass_and_the_set_hash_is_printed() -> None:
    result = run_check()

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert len([line for line in lines if line.startswith("ok ")]) == 6
    assert lines[-1].startswith("fixture set hash ")
    assert len(lines[-1].split()[-1]) == 64


def test_a_bad_span_and_a_bad_fact_exit_nonzero_and_are_named(tmp_path: Path) -> None:
    source = next(path for path in FIXTURES.iterdir() if path.name.startswith("greenhouse-"))
    copy = tmp_path / source.name
    shutil.copytree(source, copy)
    labels = (copy / "labels.yaml").read_text(encoding="utf-8")
    labels = labels.replace("F-0013", "F-9999", 1).replace(
        "span: Practical experience", "span: Xx", 1
    )
    (copy / "labels.yaml").write_text(labels, encoding="utf-8")

    result = run_check("--fixtures", str(tmp_path))

    assert result.returncode == 1
    assert "F-9999 is not in the sample bank" in result.stderr
    assert "ok " not in result.stdout


def test_an_empty_fixture_directory_is_an_error(tmp_path: Path) -> None:
    result = run_check("--fixtures", str(tmp_path))

    assert result.returncode == 1
    assert "no posting fixtures found" in result.stderr
