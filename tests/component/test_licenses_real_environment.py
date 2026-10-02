# ABOUTME: Runs the license checker against the real installed environment.
# ABOUTME: Fails if any current dependency has a license outside the allow list.
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_installed_dependencies_pass_the_license_check(tmp_path: Path) -> None:
    report = tmp_path / "licenses.json"
    licenses = subprocess.run(
        [sys.executable, "-m", "piplicenses", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    report.write_text(licenses.stdout, encoding="utf8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_licenses.py"),
            str(report),
            "--exceptions",
            str(ROOT / "license-exceptions.toml"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
