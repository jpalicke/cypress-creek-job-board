# ABOUTME: Fails when an installed dependency carries a license outside the allow list.
# ABOUTME: Reads pip-licenses JSON and a reviewed exceptions file, every exception needs a reason.
import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ALLOWED = {
    "mit",
    "mit license",
    "bsd",
    "bsd license",
    "bsd-2-clause",
    "bsd-3-clause",
    "apache-2.0",
    "apache software license",
    "isc",
    "isc license",
    "psf-2.0",
    "python software foundation license",
    "mpl-2.0",
    "mozilla public license 2.0 (mpl 2.0)",
}


@dataclass(frozen=True)
class Violation:
    name: str
    version: str
    license: str


class Exceptions:
    """Packages allowed despite their license, each with a written reason."""

    def __init__(self, reasons: dict[str, str]) -> None:
        self.reasons = reasons

    @classmethod
    def load(cls, path: Path) -> "Exceptions":
        if not path.exists():
            return cls({})
        entries = tomllib.loads(path.read_text(encoding="utf8")).get("exception", [])
        reasons: dict[str, str] = {}
        for entry in entries:
            if not entry.get("reason", "").strip():
                raise ValueError(f"exception for {entry.get('package')} needs a reason")
            reasons[entry["package"]] = entry["reason"]
        return cls(reasons)


def is_allowed(expression: str) -> bool:
    """OR needs one allowed alternative, AND and semicolons need every part allowed."""
    for alternative in re.split(r"\s+OR\s+", expression, flags=re.IGNORECASE):
        parts = re.split(r"\s+AND\s+|;", alternative, flags=re.IGNORECASE)
        if all(part.strip().lower() in ALLOWED for part in parts):
            return True
    return False


def check(report: list[dict[str, str]], exceptions: Exceptions) -> list[Violation]:
    return [
        Violation(item["Name"], item["Version"], item["License"])
        for item in report
        if item["Name"] not in exceptions.reasons and not is_allowed(item["License"])
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check dependency licenses against the allow list."
    )
    parser.add_argument("report", type=Path, help="pip-licenses --format=json output")
    parser.add_argument("--exceptions", type=Path, default=Path("license-exceptions.toml"))
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf8"))
    violations = check(report, Exceptions.load(args.exceptions))
    for v in violations:
        print(f"DISALLOWED LICENSE: {v.name} {v.version}: {v.license}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
