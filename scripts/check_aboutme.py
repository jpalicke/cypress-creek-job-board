# ABOUTME: Fails when a code file does not start with the two line ABOUTME header.
# ABOUTME: Checks structure only, in the comment syntax of each language, a shebang may come first.
import sys
from pathlib import Path

PREFIX = "ABOUTME: "
LINE_COMMENT = {
    ".py": "# ",
    ".sh": "# ",
    ".ts": "// ",
    ".tsx": "// ",
    ".js": "// ",
    ".mjs": "// ",
    ".cjs": "// ",
    ".sql": "-- ",
}
SVELTE = ".svelte"


def expected_line(suffix: str, line: str) -> bool:
    if suffix == SVELTE:
        return line.startswith("<!-- " + PREFIX) and line.rstrip().endswith(" -->")
    return line.startswith(LINE_COMMENT[suffix] + PREFIX)


def check_file(path: Path) -> str | None:
    """Return a problem description, or None when the file passes or is not code."""
    suffix = path.suffix
    if suffix != SVELTE and suffix not in LINE_COMMENT:
        return None
    lines = path.read_text(encoding="utf8").splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    if len(lines) < 2 or not all(expected_line(suffix, line) for line in lines[:2]):
        return f"{path}: first two lines must be ABOUTME comments"
    return None


def main(argv: list[str] | None = None) -> int:
    paths = sys.argv[1:] if argv is None else argv
    problems = [p for p in (check_file(Path(arg)) for arg in paths) if p]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
