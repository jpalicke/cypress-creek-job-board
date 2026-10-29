# ABOUTME: Proves draft help cannot send, copy or apply: no network, clipboard or process use.
# ABOUTME: Drafting only returns data, a person copies the text by hand.
import ast
from pathlib import Path

DRAFT_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "cypress_creek" / "pipeline" / "draft.py"
)
FORBIDDEN_ROOTS = {
    "httpx",
    "requests",
    "urllib",
    "http",
    "socket",
    "smtplib",
    "email",
    "subprocess",
    "webbrowser",
    "pyperclip",
    "ftplib",
    "os",
    "shutil",
    "sqlite3",
}


def _imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_draft_module_imports_nothing_that_can_send_or_copy() -> None:
    assert _imported_roots(DRAFT_SOURCE.read_text(encoding="utf-8")) & FORBIDDEN_ROOTS == set()


def test_draft_module_never_calls_a_provider_outside_the_one_structured_call() -> None:
    source = DRAFT_SOURCE.read_text(encoding="utf-8")
    assert source.count(".complete_structured(") == 1
    for name in ("open(", "write_text(", "print(", "exec(", "eval("):
        assert name not in source
