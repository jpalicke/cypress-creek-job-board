# ABOUTME: The scorer: reads run files and committed hand labels, writes a metrics JSON per run.
# ABOUTME: Also prints a per case mismatch view. The same files always give the same numbers.
import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cypress_creek.eval_records import RunState, load_run
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.facts.models import Bank
from evals.harness.fixtures import Fixture, discover_fixtures, load_fixture
from evals.harness.labels import LabelError, LabelsNotCommitted, require_committed_labels
from evals.harness.metrics import (
    METRICS,
    CaseScore,
    MetricValue,
    MissedGap,
    ScoreError,
    aggregate,
    pool,
    repeat_values,
    score_case,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = ROOT / "evals" / "fixtures"
DEFAULT_BANK = ROOT / "evals" / "bank" / "sample_bank.yaml"
FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class RunMetrics(BaseModel):
    """The scored result of one run, or `not_run` for a backend that has no run file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: str
    model: str | None
    run_id: str | None
    run_status: Literal["complete", "incomplete", "failed", "not_run"]
    repeats_planned: int
    repeats_scored: int
    cases: list[str]
    metrics: dict[str, MetricValue]
    missed_planted_gaps: list[MissedGap]


def not_run(backend: str) -> RunMetrics:
    return RunMetrics(
        backend=backend,
        model=None,
        run_id=None,
        run_status="not_run",
        repeats_planned=0,
        repeats_scored=0,
        cases=[],
        metrics=aggregate([]),
        missed_planted_gaps=[],
    )


def score_cases(state: RunState, fixtures: Mapping[str, Fixture], bank: Bank) -> list[CaseScore]:
    """Score every recorded case against its fixture, refusing a run that used other inputs."""
    if state.header.bank_hash != bank_hash(bank):
        raise ScoreError("the run used a different bank than the one given")
    scores = []
    for case in sorted(state.cases, key=lambda item: (item.repeat, item.case_id)):
        fixture = fixtures.get(case.case_id)
        if fixture is None:
            raise ScoreError(f"no fixture for case {case.case_id}")
        if case.posting_hash != fixture.text_hash:
            raise ScoreError(f"the posting of case {case.case_id} differs from its fixture")
        scores.append(
            score_case(
                fixture.labels,
                fixture.text,
                case.report,
                bank,
                case_id=case.case_id,
                repeat=case.repeat,
            )
        )
    return scores


def summarize(state: RunState, scores: Sequence[CaseScore]) -> RunMetrics:
    """Metrics of the repeats that have every planned case. A partial repeat is not scored."""
    header = state.header
    per_repeat = []
    for repeat in range(1, header.repeats + 1):
        chosen = [score for score in scores if score.repeat == repeat]
        if {score.case_id for score in chosen} == set(header.case_ids):
            per_repeat.append((repeat, chosen))
    return RunMetrics(
        backend=header.backend,
        model=header.model,
        run_id=header.run_id,
        run_status=state.status,
        repeats_planned=header.repeats,
        repeats_scored=len(per_repeat),
        cases=list(header.case_ids),
        metrics=aggregate([repeat_values(pool(chosen)) for _, chosen in per_repeat]),
        missed_planted_gaps=[
            gap
            for repeat, chosen in per_repeat
            for score in chosen
            for gap in score.missed
            if gap.repeat == repeat
        ],
    )


def score_run(state: RunState, fixtures: Mapping[str, Fixture], bank: Bank) -> RunMetrics:
    return summarize(state, score_cases(state, fixtures, bank))


def render_summary(result: RunMetrics) -> str:
    head = (
        f"{result.backend} {result.model or '-'} run {(result.run_id or '-')[:12]} "
        f"({result.run_status}, repeats scored {result.repeats_scored} of {result.repeats_planned})"
    )
    lines = [head]
    for metric in METRICS:
        value = result.metrics[metric.name]
        shown = (
            "not run"
            if value.mean is None or value.worst is None
            else f"mean {value.mean:.3f} worst {value.worst:.3f}"
        )
        lines.append(f"  {metric.experiment} {metric.name:31} {shown}")
    return "\n".join(lines)


def render_diff(result: RunMetrics, scores: Sequence[CaseScore]) -> str:
    """Every mismatch line in case and repeat order, then the planted gaps the run missed."""
    lines = [line for score in scores for line in score.mismatches]
    lines.append("Missed planted gaps:")
    if not result.missed_planted_gaps:
        lines.append("  none")
    for gap in result.missed_planted_gaps:
        cited = ", ".join(gap.fact_ids) or "no facts"
        lines.append(
            f"  {gap.case_id} repeat {gap.repeat} {gap.label_id} ({gap.planted_gap}): "
            f"claimed {gap.claimed.value}, cited {cited}"
        )
    return "\n".join(lines)


def _load_fixtures(root: Path, needed: set[str]) -> dict[str, Fixture]:
    """Load the fixtures a run names. Their labels must be committed and unchanged in git."""
    by_id: dict[str, Path] = {path.name: path for path in discover_fixtures(root)}
    loaded: dict[str, Fixture] = {}
    for case_id in sorted(needed):
        directory = by_id.get(case_id)
        if directory is None:
            raise ScoreError(f"no fixture for case {case_id}")
        require_committed_labels(directory)
        loaded[case_id] = load_fixture(directory)
    return loaded


def _write(out: Path, name: str, result: RunMetrics) -> bool:
    out.mkdir(parents=True, exist_ok=True)
    try:
        with (out / name).open("x", encoding="utf-8") as target:
            target.write(result.model_dump_json(indent=2) + "\n")
    except FileExistsError:
        print(f"refusing to overwrite {out / name}", file=sys.stderr)
        return False
    return True


def _file_name(result: RunMetrics) -> str:
    if result.run_id is None:
        return f"{FILENAME_UNSAFE.sub('_', result.backend)}-not-run.json"
    parts = (result.backend, result.model or "", result.run_id[:12])
    return "-".join(FILENAME_UNSAFE.sub("_", part) for part in parts) + ".json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score eval run files against hand labels.")
    parser.add_argument("--run", type=Path, action="append", default=[], help="a JSONL run export")
    parser.add_argument("--expect-backend", action="append", default=[], metavar="NAME")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    parser.add_argument("--out", type=Path, required=True, help="directory for the metrics JSON")
    parser.add_argument("--diff", action="store_true", help="print every mismatch per case")
    args = parser.parse_args(argv)

    try:
        return _score_all(args)
    except (ScoreError, LabelError, LabelsNotCommitted, ValueError, OSError) as error:
        print(f"score failed: {error}", file=sys.stderr)
        return 1


def _score_all(args: argparse.Namespace) -> int:
    bank = load_bank(args.bank, strict=True)
    states = [load_run(path) for path in args.run]
    needed = {case_id for state in states for case_id in state.header.case_ids}
    fixtures = _load_fixtures(args.fixtures, needed)
    results: list[tuple[RunMetrics, list[CaseScore]]] = []
    for state in states:
        scores = score_cases(state, fixtures, bank)
        results.append((summarize(state, scores), scores))
    seen = {result.backend for result, _ in results}
    results += [(not_run(name), []) for name in args.expect_backend if name not in seen]
    ok = True
    for result, scores in results:
        ok = _write(args.out, _file_name(result), result) and ok
        print(render_summary(result))
        if args.diff and scores:
            print(render_diff(result, scores))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
