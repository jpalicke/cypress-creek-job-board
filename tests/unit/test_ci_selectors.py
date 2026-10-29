# ABOUTME: Checks that every test marked live is selected by the live workflow, and by no other one.
# ABOUTME: A live test that no workflow runs would pass unnoticed, so the selectors are tested.
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
TESTS = ROOT / "tests"
LIVE_MARK = re.compile(r"pytest\.mark\.live\b(?!_)")


def _pytest_line(workflow: str) -> str:
    lines = [
        line.strip()
        for line in (WORKFLOWS / workflow).read_text(encoding="utf-8").splitlines()
        if "pytest tests" in line and " -m " in line
    ]
    assert len(lines) == 1, (
        f"{workflow} should have exactly one marker-selected pytest run, got {lines}"
    )
    return lines[0]


def _live_test_dirs() -> set[str]:
    return {
        path.parent.name
        for path in TESTS.rglob("test_*.py")
        if path.parent.name != "unit"
        if LIVE_MARK.search(path.read_text(encoding="utf-8"))
    }


def test_the_live_workflow_runs_every_directory_that_holds_a_live_test() -> None:
    line = _pytest_line("live.yml")
    missing = {name for name in _live_test_dirs() if f"tests/{name}" not in line}
    assert missing == set(), f"live.yml does not select tests/{sorted(missing)}"


def test_the_live_workflow_selects_live_tests_that_need_no_key_or_internet() -> None:
    line = _pytest_line("live.yml")
    assert '-m "live and not needs_network and not live_openai and not live_lmstudio"' in line


def test_no_other_workflow_runs_live_tests() -> None:
    for name in ("deterministic.yml", "network.yml"):
        marker_expression = _pytest_line(name).split("-m", 1)[1]
        assert "not live " in marker_expression or 'not live"' in marker_expression
