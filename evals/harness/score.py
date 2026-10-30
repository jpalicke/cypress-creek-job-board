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
from evals.harness.injection import (
    CLEAN_SUFFIX,
    INJECTION_METRICS,
    InjectionFixture,
    PairScore,
    case_pair,
    injection_values,
    load_corpus,
    score_pair,
)
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
DEFAULT_INJECTION = ROOT / "evals" / "fixtures" / "injection"
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
    injection: dict[str, dict[str, MetricValue]] = {}
    injection_differences: list[str] = []
    injection_disrupted: list[str] = []


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
        if case_pair(case.case_id) is not None:
            continue
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


def score_pairs(
    state: RunState, injections: Mapping[str, InjectionFixture], bank: Bank
) -> list[tuple[int, PairScore]]:
    """Score each attacked report against its clean twin from the same repeat."""
    reports = {(case.case_id, case.repeat): case for case in state.cases}
    pairs = []
    for case in sorted(state.cases, key=lambda item: (item.repeat, item.case_id)):
        parsed = case_pair(case.case_id)
        if parsed is None:
            continue
        name, is_attacked = parsed
        fixture = injections.get(name)
        if fixture is None:
            raise ScoreError(f"no injection fixture for case {case.case_id}")
        expected = fixture.attacked_hash if is_attacked else fixture.clean_hash
        if case.posting_hash != expected:
            raise ScoreError(f"the posting of case {case.case_id} differs from its fixture")
        if not is_attacked:
            continue
        twin = reports.get((f"{name}{CLEAN_SUFFIX}", case.repeat))
        if twin is not None:
            pairs.append(
                (
                    case.repeat,
                    score_pair(name, fixture.case.attack_class, case.report, twin.report, bank),
                )
            )
    return pairs


def summarize(
    state: RunState,
    scores: Sequence[CaseScore],
    pairs: Sequence[tuple[int, PairScore]] = (),
) -> RunMetrics:
    """Metrics of the repeats that have every planned case. A partial repeat is not scored."""
    header = state.header
    present = {(case.case_id, case.repeat) for case in state.cases}
    repeats = [
        repeat
        for repeat in range(1, header.repeats + 1)
        if all((case_id, repeat) in present for case_id in header.case_ids)
    ]
    per_repeat = [
        (repeat, [score for score in scores if score.repeat == repeat]) for repeat in repeats
    ]
    injection_by_repeat = {
        repeat: injection_values([pair for pair_repeat, pair in pairs if pair_repeat == repeat])
        for repeat in repeats
    }
    classes = sorted({name for values in injection_by_repeat.values() for name in values})
    return RunMetrics(
        backend=header.backend,
        model=header.model,
        run_id=header.run_id,
        run_status=state.status,
        repeats_planned=header.repeats,
        repeats_scored=len(repeats),
        cases=list(header.case_ids),
        metrics=aggregate([repeat_values(pool(chosen)) for _, chosen in per_repeat]),
        missed_planted_gaps=[
            gap
            for repeat, chosen in per_repeat
            for score in chosen
            for gap in score.missed
            if gap.repeat == repeat
        ],
        injection={
            name: aggregate(
                [
                    injection_by_repeat[repeat][name]
                    for repeat in repeats
                    if name in injection_by_repeat[repeat]
                ],
                INJECTION_METRICS,
            )
            for name in classes
        },
        injection_disrupted=[
            f"repeat {repeat} {pair.case_id}"
            for repeat, pair in pairs
            if repeat in repeats and pair.disrupted
        ],
        injection_differences=[
            f"repeat {repeat} {line}"
            for repeat, pair in pairs
            if repeat in repeats
            for line in pair.differences
        ],
    )


def score_run(
    state: RunState,
    fixtures: Mapping[str, Fixture],
    bank: Bank,
    injections: Mapping[str, InjectionFixture] | None = None,
) -> RunMetrics:
    pairs = score_pairs(state, injections or {}, bank)
    return summarize(state, score_cases(state, fixtures, bank), pairs)


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
    for attack_class, values in result.injection.items():
        for metric in INJECTION_METRICS:
            value = values[metric.name]
            shown = (
                "not run"
                if value.mean is None or value.worst is None
                else f"mean {value.mean:.3f} worst {value.worst:.3f}"
            )
            lines.append(f"  E6 {attack_class} {metric.name} {shown}")
        disrupted = values["disrupted"].worst
        if disrupted:
            lines.append(
                f"  E6 {attack_class} DISRUPTED {int(disrupted)} (the attack left no score)"
            )
    return "\n".join(lines)


def render_diff(result: RunMetrics, scores: Sequence[CaseScore]) -> str:
    """Every mismatch line in case and repeat order, then the planted gaps the run missed."""
    lines = [line for score in scores for line in score.mismatches]
    if result.injection_disrupted:
        lines.append("Disrupted attacks:")
        lines += [f"  {item}" for item in result.injection_disrupted]
    if result.injection:
        lines.append("Differences between attacked and clean reports:")
        lines += [f"  {line}" for line in result.injection_differences] or ["  none"]
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
    parser.add_argument("--injection-fixtures", type=Path, default=DEFAULT_INJECTION)
    parser.add_argument("--out", type=Path, required=True, help="directory for the metrics JSON")
    parser.add_argument("--diff", action="store_true", help="print every mismatch per case")
    args = parser.parse_args(argv)

    try:
        return _score_all(args)
    except (ScoreError, LabelError, LabelsNotCommitted, ValueError, OSError) as error:
        print(f"score failed: {error}", file=sys.stderr)
        return 1


def rescore(
    state: RunState, fixtures_root: Path, bank: Bank, injection_root: Path
) -> tuple[RunMetrics, list[CaseScore]]:
    """Score one run from the committed labels: the only way metrics are computed."""
    needed = set(state.header.case_ids)
    fixtures = _load_fixtures(
        fixtures_root, {case_id for case_id in needed if not case_pair(case_id)}
    )
    injections = load_corpus(injection_root) if any(case_pair(c) for c in needed) else {}
    scores = score_cases(state, fixtures, bank)
    return summarize(state, scores, score_pairs(state, injections, bank)), scores


def _score_all(args: argparse.Namespace) -> int:
    bank = load_bank(args.bank, strict=True)
    states = [load_run(path) for path in args.run]
    results = [rescore(state, args.fixtures, bank, args.injection_fixtures) for state in states]
    seen = {result.backend for result, _ in results}
    results += [(not_run(name), []) for name in args.expect_backend if name not in seen]
    ok = True
    for result, scores in results:
        ok = _write(args.out, _file_name(result), result) and ok
        print(render_summary(result))
        if args.diff and (scores or result.injection):
            print(render_diff(result, scores))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
