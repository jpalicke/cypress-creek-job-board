# ABOUTME: Runs the committed-labels guard in a child process inside a real merge in progress.
# ABOUTME: Labels the merge brought in pass, and a hand edit made during the merge is refused.
import subprocess
import sys
from pathlib import Path

CHILD = (
    "import sys\n"
    "from pathlib import Path\n"
    "from evals.harness.labels import LabelsNotCommitted, require_committed_labels\n"
    "try:\n"
    "    require_committed_labels(Path(sys.argv[1]))\n"
    "except LabelsNotCommitted as error:\n"
    "    print('refused:', error)\n"
    "    sys.exit(3)\n"
    "print('accepted')\n"
)


def git(directory: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=directory,
        check=True,
        capture_output=True,
    )


def guard(fixture: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", CHILD, str(fixture)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_a_merge_in_progress_passes_and_a_hand_edit_during_it_is_refused(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    labels = fixture / "labels.yaml"
    labels.write_text("a: 1\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "labels")
    git(tmp_path, "checkout", "-q", "-b", "side")
    labels.write_text("a: 2\n", encoding="utf-8")
    git(tmp_path, "commit", "-q", "-am", "side labels")
    git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "main moves on")
    git(tmp_path, "merge", "-q", "--no-commit", "--no-ff", "side")

    merged = guard(fixture)
    assert (merged.returncode, merged.stdout.strip(), merged.stderr) == (0, "accepted", "")

    labels.write_text("a: 3\n", encoding="utf-8")
    edited = guard(fixture)
    assert edited.returncode == 3
    assert edited.stdout.startswith("refused:")
