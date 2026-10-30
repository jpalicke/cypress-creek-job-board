# ABOUTME: Tests the license checker against recorded real pip-licenses reports.
# ABOUTME: agpl_report.json is the clean report with one package hand edited to AGPL.
import json
from pathlib import Path

import pytest
from check_licenses import Exceptions, check, main, npm_report

FIXTURES = Path(__file__).parent.parent / "fixtures" / "licenses"
NO_EXCEPTIONS = Exceptions({})


def load(name: str) -> list[dict[str, str]]:
    data: list[dict[str, str]] = json.loads((FIXTURES / name).read_text(encoding="utf8"))
    return data


def test_disallowed_license_is_flagged() -> None:
    violations = check(load("agpl_report.json"), NO_EXCEPTIONS)
    assert [v.name for v in violations] == ["ast_serialize"]


def test_clean_report_passes() -> None:
    assert check(load("clean_report.json"), NO_EXCEPTIONS) == []


def test_exception_with_reason_allows_the_package() -> None:
    exceptions = Exceptions({"ast_serialize": "reviewed, build time only"})
    assert check(load("agpl_report.json"), exceptions) == []


def test_unknown_license_is_flagged() -> None:
    report = [{"Name": "mystery", "Version": "1", "License": "UNKNOWN"}]
    assert [v.name for v in check(report, NO_EXCEPTIONS)] == ["mystery"]


def test_or_expression_passes_when_one_alternative_is_allowed() -> None:
    report = [{"Name": "dual", "Version": "1", "License": "GPL-3.0 OR MIT"}]
    assert check(report, NO_EXCEPTIONS) == []


def test_and_expression_fails_when_one_part_is_disallowed() -> None:
    report = [{"Name": "both", "Version": "1", "License": "MIT AND AGPL-3.0"}]
    assert [v.name for v in check(report, NO_EXCEPTIONS)] == ["both"]


def test_exception_without_reason_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "exceptions.toml"
    path.write_text('[[exception]]\npackage = "x"\nreason = ""\n', encoding="utf8")
    with pytest.raises(ValueError, match="reason"):
        Exceptions.load(path)


def test_main_exit_code_is_nonzero_for_disallowed_license(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([str(FIXTURES / "agpl_report.json"), "--exceptions", str(FIXTURES / "none.toml")])
    assert code == 1
    assert "ast_serialize" in capsys.readouterr().out


def test_main_exit_code_is_zero_for_clean_report(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(FIXTURES / "clean_report.json"), "--exceptions", str(FIXTURES / "none.toml")])
    assert code == 0
    capsys.readouterr()


LOCKFILE = Path(__file__).parent.parent.parent / "web" / "package-lock.json"


def test_npm_lockfile_entries_become_a_license_report() -> None:
    lock = {
        "packages": {
            "": {"name": "root"},
            "node_modules/a": {"version": "1.0.0", "license": "MIT"},
            "node_modules/a/node_modules/@scope/b": {"version": "2.0.0", "license": "ISC"},
            "node_modules/c": {"version": "3.0.0"},
        }
    }
    assert npm_report(lock) == [
        {"Name": "a", "Version": "1.0.0", "License": "MIT"},
        {"Name": "@scope/b", "Version": "2.0.0", "License": "ISC"},
        {"Name": "c", "Version": "3.0.0", "License": "UNKNOWN"},
    ]


def test_the_real_web_lockfile_passes_the_allow_list() -> None:
    lock = json.loads(LOCKFILE.read_text(encoding="utf8"))
    report = npm_report(lock)
    assert len(report) > 50
    assert check(report, Exceptions.load(Path("license-exceptions.toml"))) == []


def test_a_disallowed_npm_package_is_flagged() -> None:
    lock = json.loads(LOCKFILE.read_text(encoding="utf8"))
    first = next(key for key in lock["packages"] if key)
    lock["packages"][first]["license"] = "AGPL-3.0"
    violations = check(npm_report(lock), NO_EXCEPTIONS)
    assert [v.license for v in violations] == ["AGPL-3.0"]


def test_main_checks_an_npm_lockfile(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    lock = tmp_path / "package-lock.json"
    lock.write_text(
        json.dumps({"packages": {"node_modules/x": {"version": "1", "license": "GPL-3.0"}}}),
        encoding="utf8",
    )
    code = main(["--npm-lock", str(lock), "--exceptions", str(FIXTURES / "none.toml")])
    assert code == 1
    assert "x 1: GPL-3.0" in capsys.readouterr().out
    clean = tmp_path / "clean.json"
    clean.write_text(
        json.dumps({"packages": {"node_modules/x": {"version": "1", "license": "MIT"}}}),
        encoding="utf8",
    )
    assert main(["--npm-lock", str(clean), "--exceptions", str(FIXTURES / "none.toml")]) == 0
