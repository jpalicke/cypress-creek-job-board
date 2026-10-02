# ABOUTME: Tests the ABOUTME header check against real files written to temp directories.
# ABOUTME: Covers each supported comment syntax, shebangs, malformed headers and skipped file types.
from pathlib import Path

import pytest
from check_aboutme import check_file, main

GOOD = {
    "a.py": "# ABOUTME: Does a thing.\n# ABOUTME: In more detail.\nx = 1\n",
    "a.sh": "# ABOUTME: Does a thing.\n# ABOUTME: In more detail.\necho hi\n",
    "a.ts": "// ABOUTME: Does a thing.\n// ABOUTME: In more detail.\nexport {};\n",
    "a.js": "// ABOUTME: Does a thing.\n// ABOUTME: In more detail.\n",
    "a.sql": "-- ABOUTME: Does a thing.\n-- ABOUTME: In more detail.\nselect 1;\n",
    "a.svelte": "<!-- ABOUTME: Does a thing. -->\n<!-- ABOUTME: In more detail. -->\n<p>x</p>\n",
}


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf8")
    return path


def test_file_without_header_fails(tmp_path: Path) -> None:
    assert check_file(write(tmp_path, "a.py", "x = 1\n")) is not None


def test_one_aboutme_line_and_a_blank_second_line_fails(tmp_path: Path) -> None:
    assert check_file(write(tmp_path, "a.py", "# ABOUTME: Only one.\n\nx = 1\n")) is not None


def test_empty_file_fails(tmp_path: Path) -> None:
    assert check_file(write(tmp_path, "a.py", "")) is not None


@pytest.mark.parametrize("name", sorted(GOOD))
def test_correct_header_passes_in_each_language(tmp_path: Path, name: str) -> None:
    assert check_file(write(tmp_path, name, GOOD[name])) is None


@pytest.mark.parametrize("name", ["a.py", "a.ts", "a.sql", "a.svelte"])
def test_wrong_comment_syntax_fails(tmp_path: Path, name: str) -> None:
    text = "/* ABOUTME: one */\n/* ABOUTME: two */\n"
    assert check_file(write(tmp_path, name, text)) is not None


def test_missing_space_after_prefix_fails(tmp_path: Path) -> None:
    assert check_file(write(tmp_path, "a.py", "# ABOUTME:x\n# ABOUTME: y\n")) is not None


def test_shebang_before_header_is_allowed(tmp_path: Path) -> None:
    text = "#!/usr/bin/env bash\n" + GOOD["a.sh"]
    assert check_file(write(tmp_path, "run.sh", text)) is None


@pytest.mark.parametrize("name", ["a.md", "a.json", "a.yaml", "uv.lock", "a.txt"])
def test_non_code_files_are_skipped(tmp_path: Path, name: str) -> None:
    assert check_file(write(tmp_path, name, "no header here\n")) is None


def test_main_reports_failures_and_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = write(tmp_path, "bad.py", "x = 1\n")
    good = write(tmp_path, "good.py", GOOD["a.py"])
    assert main([str(bad), str(good)]) == 1
    out = capsys.readouterr().out
    assert "bad.py" in out
    assert "good.py" not in out


def test_main_returns_zero_when_all_files_pass(tmp_path: Path) -> None:
    assert main([str(write(tmp_path, "good.py", GOOD["a.py"]))]) == 0
