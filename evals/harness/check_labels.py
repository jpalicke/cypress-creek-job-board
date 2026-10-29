# ABOUTME: Command line check of every posting fixture: files, hashes, labels and the set hash.
# ABOUTME: Exits 1 and prints each problem on standard error when any fixture is unsound.
import argparse
import sys
from pathlib import Path

from cypress_creek.facts import load_bank
from evals.harness.fixtures import discover_fixtures, fixture_set_hash, load_fixture
from evals.harness.labels import LabelError, planted_gap_support, validate_labels

ROOT = Path(__file__).parent.parent.parent
DEFAULT_FIXTURES = ROOT / "evals" / "fixtures"
BANK_PATH = ROOT / "evals" / "bank" / "sample_bank.yaml"
PLANTED_PATH = ROOT / "evals" / "bank" / "PLANTED_GAPS.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate posting fixtures and their hand labels.")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    args = parser.parse_args(argv)

    directories = discover_fixtures(args.fixtures)
    if not directories:
        print(f"no posting fixtures found in {args.fixtures}", file=sys.stderr)
        return 1
    bank = load_bank(BANK_PATH, strict=True)
    planted = planted_gap_support(PLANTED_PATH)
    fixtures = []
    failed = False
    for directory in directories:
        try:
            fixture = load_fixture(directory)
            validate_labels(fixture.labels, fixture.text, bank, planted)
        except LabelError as error:
            failed = True
            for problem in error.problems:
                print(f"{directory.name}: {problem}", file=sys.stderr)
            continue
        fixtures.append(fixture)
        print(f"ok {directory.name} {len(fixture.labels.requirements)} requirements")
    if failed:
        return 1
    print(f"fixture set hash {fixture_set_hash(fixtures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
