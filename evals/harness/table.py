# ABOUTME: Builds the backend comparison table from scored run files; it is never hand made.
# ABOUTME: Writes docs/evals-results.md and the README block, and --check fails if they are stale.
import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from cypress_creek.eval_records import RunState, load_run
from cypress_creek.facts import load_bank
from evals.harness.labels import LabelError, LabelsNotCommitted
from evals.harness.metrics import MetricValue, ScoreError
from evals.harness.score import (
    DEFAULT_BANK as DEFAULT_SCORE_BANK,
)
from evals.harness.score import (
    DEFAULT_FIXTURES,
    DEFAULT_INJECTION,
    RunMetrics,
    rescore,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = ROOT / "evals" / "results"
DEFAULT_BACKENDS = ROOT / "evals" / "backends.yaml"
DEFAULT_PAGE = ROOT / "docs" / "evals-results.md"
DEFAULT_README = ROOT / "README.md"
README_START = "<!-- evals-results:start -->"
README_END = "<!-- evals-results:end -->"
HASH_CHARS = 12
SCHEMA_FAILURE = "SchemaViolation"
NOT_RUN = "not run"
NOT_RECORDED = "not recorded"


class TableError(Exception):
    """The table cannot be built or is out of date. The message says what to do."""


@dataclass(frozen=True)
class Cell:
    """A metric as mean and worst of the repeats. Both None means no repeat measured it."""

    mean: float | None
    worst: float | None


@dataclass(frozen=True)
class Row:
    label: str
    model: str | None
    status: str
    repeats: str
    commit: str | None
    prompt_hash: str | None
    fixture_hash: str | None
    recall: Cell
    violations: Cell
    score_shift: Cell
    disrupted: int | None
    schema_failures: Cell
    latency: Cell
    cost: Cell

    @classmethod
    def not_run(cls, label: str) -> "Row":
        empty = Cell(None, None)
        return cls(
            label,
            None,
            NOT_RUN,
            NOT_RUN,
            None,
            None,
            None,
            empty,
            empty,
            empty,
            None,
            empty,
            empty,
            empty,
        )

    @property
    def was_run(self) -> bool:
        return self.status != NOT_RUN


COLUMNS = (
    "Target",
    "Model",
    "Status",
    "Repeats scored",
    "E1 recall",
    "E3 violations per 100",
    "E6 worst class max abs shift",
    "E6 disrupted",
    "E8 schema failure rate",
    "Median latency",
    "Cost per run, USD",
    "Commit",
    "Prompt hash",
    "Fixture hash",
    "Conditions",
)


def short_hash(hashes: Mapping[str, str]) -> str:
    canonical = json.dumps(dict(hashes), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:HASH_CHARS]


def _pair(cell: Cell, places: int) -> str:
    if cell.mean is None or cell.worst is None:
        return NOT_RUN
    return f"{cell.mean:.{places}f} / {cell.worst:.{places}f}"


def _groups(rows: Sequence[Row]) -> dict[tuple[str | None, str | None], str]:
    letters: dict[tuple[str | None, str | None], str] = {}
    for row in rows:
        key = (row.prompt_hash, row.fixture_hash)
        if row.was_run and key not in letters:
            letters[key] = chr(ord("A") + len(letters))
    return letters


def _conditions(row: Row, letters: Mapping[tuple[str | None, str | None], str]) -> str:
    if not row.was_run:
        return "-"
    letter = letters[(row.prompt_hash, row.fixture_hash)]
    if len(letters) == 1 or letter == "A":
        return letter
    return f"{letter} (not comparable with A)"


def _cells(row: Row, letters: Mapping[tuple[str | None, str | None], str]) -> list[str]:
    if not row.was_run:
        return [row.label, NOT_RUN, NOT_RUN, NOT_RUN, *[NOT_RUN] * 7, "-", "-", "-", "-"]
    latency = _pair(row.latency, 3) if row.latency.mean is not None else NOT_RECORDED
    return [
        row.label,
        row.model or "-",
        row.status,
        row.repeats,
        _pair(row.recall, 3),
        _pair(row.violations, 3),
        _pair(row.score_shift, 3),
        NOT_RUN if row.disrupted is None else str(row.disrupted),
        _pair(row.schema_failures, 3),
        latency,
        _pair(row.cost, 4),
        row.commit or "-",
        row.prompt_hash or "-",
        row.fixture_hash or "-",
        _conditions(row, letters),
    ]


def render_table(rows: Sequence[Row]) -> str:
    """A Markdown table, then one line saying whether the run rows can be compared."""
    letters = _groups(rows)
    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    lines += ["| " + " | ".join(_cells(row, letters)) + " |" for row in rows]
    if not letters:
        note = "No backend has been run yet, so every row is not run."
    elif len(letters) == 1:
        note = "All run rows were produced under the same prompt hash and fixture set."
    else:
        note = (
            "The run rows were produced under different prompt hashes or fixture sets "
            "(see Conditions), so rows in different groups are not comparable."
        )
    return "\n".join(lines) + "\n\n" + note + "\n"


class Target(BaseModel):
    """A backend the table must list. `model` None accepts any model of that backend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    backend: str
    model: str | None = None


class Targets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    targets: list[Target]


def load_targets(path: Path) -> list[Target]:
    try:
        return Targets.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).targets
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise TableError(
            f"cannot read the backend list {path.name}: {type(error).__name__}"
        ) from None


@dataclass(frozen=True)
class ScoredRun:
    metrics: RunMetrics
    state: RunState


@dataclass(frozen=True)
class Scoring:
    """Where the committed labels, the fact bank and the injection corpus are."""

    fixtures: Path
    bank: Path
    injection: Path


DEFAULT_SCORING = Scoring(DEFAULT_FIXTURES, DEFAULT_SCORE_BANK, DEFAULT_INJECTION)


def _verified(name: str, metrics: RunMetrics, state: RunState, scoring: Scoring) -> None:
    """Score the run file again from the committed labels. Metrics that differ are refused."""
    try:
        again, _ = rescore(
            state, scoring.fixtures, load_bank(scoring.bank, strict=True), scoring.injection
        )
    except (ScoreError, LabelError, LabelsNotCommitted) as error:
        raise TableError(f"cannot score the run behind {name}: {error}") from None
    if again != metrics:
        raise TableError(
            f"{name} does not match its run file scored again from the committed labels; "
            "score the run file again with the scorer"
        )


def _read_runs(results: Path, scoring: Scoring) -> list[ScoredRun]:
    """Every scored run in the folder, each metrics file paired with the run file it came from."""
    states: dict[str, RunState] = {}
    for path in sorted(results.glob("*.jsonl")):
        state = load_run(path)
        states[state.header.run_id] = state
    runs: list[ScoredRun] = []
    used: set[str] = set()
    for path in sorted(results.glob("*.json")):
        try:
            metrics = RunMetrics.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError:
            raise TableError(f"{path.name} is not a metrics file written by the scorer") from None
        if metrics.run_id is None:
            continue
        found = states.get(metrics.run_id)
        if found is None:
            raise TableError(
                f"{path.name} has no run file in {results.name}; copy the .jsonl there"
            )
        _verified(path.name, metrics, found, scoring)
        used.add(metrics.run_id)
        runs.append(ScoredRun(metrics, found))
    unscored = sorted(set(states) - used)
    if unscored:
        raise TableError(f"run {unscored[0][:12]} has no metrics file; score it with the scorer")
    return runs


def _complete_repeats(state: RunState) -> list[int]:
    wanted = set(state.header.case_ids)
    return [
        repeat
        for repeat in range(1, state.header.repeats + 1)
        if {case.case_id for case in state.cases if case.repeat == repeat} == wanted
    ]


def _spread(values: Sequence[float], *, higher_is_worse: bool) -> Cell:
    if not values:
        return Cell(None, None)
    return Cell(sum(values) / len(values), max(values) if higher_is_worse else min(values))


def _cost_and_failures(state: RunState) -> tuple[Cell, Cell]:
    """Cost per run and the share of calls that ended in a schema violation, per repeat."""
    costs: list[float] = []
    failure_rates: list[float] = []
    for repeat in _complete_repeats(state):
        calls = [call for case in state.cases if case.repeat == repeat for call in case.calls]
        if calls and all(call.cost_usd is not None for call in calls):
            costs.append(sum(call.cost_usd or 0.0 for call in calls))
        if calls:
            failed = sum(1 for call in calls if call.error_type == SCHEMA_FAILURE)
            failure_rates.append(failed / len(calls))
    return _spread(costs, higher_is_worse=True), _spread(failure_rates, higher_is_worse=True)


def _metric(run: RunMetrics, name: str) -> Cell:
    return _metric_in(run.metrics, name)


def _injection_shift(run: RunMetrics) -> Cell:
    """The worst class by max_abs_shift: its mean and worst over the repeats."""
    cells = [_metric_in(classes, "max_abs_shift") for classes in run.injection.values()]
    measured = [cell for cell in cells if cell.mean is not None and cell.worst is not None]
    if not measured:
        return Cell(None, None)
    return Cell(max(c.mean or 0.0 for c in measured), max(c.worst or 0.0 for c in measured))


def _metric_in(values: Mapping[str, MetricValue], name: str) -> Cell:
    value = values.get(name)
    if value is None or value.mean is None or value.worst is None:
        return Cell(None, None)
    return Cell(value.mean, value.worst)


def _row_for(label: str, run: ScoredRun) -> Row:
    header = run.state.header
    cost, failures = _cost_and_failures(run.state)
    return Row(
        label=label,
        model=header.model,
        status=run.metrics.run_status,
        repeats=f"{run.metrics.repeats_scored} of {run.metrics.repeats_planned}",
        commit=header.git_commit[:HASH_CHARS],
        prompt_hash=short_hash(header.prompt_hashes),
        fixture_hash=header.fixture_set_hash[:HASH_CHARS],
        recall=_metric(run.metrics, "requirement_recall"),
        violations=_metric(run.metrics, "grounding_violations_per_100"),
        score_shift=_injection_shift(run.metrics),
        disrupted=len(run.metrics.injection_disrupted) if run.metrics.injection else None,
        schema_failures=failures,
        latency=Cell(None, None),
        cost=cost,
    )


def _target_for(run: ScoredRun, targets: Sequence[Target]) -> Target | None:
    backend, model = run.metrics.backend, run.metrics.model
    exact = [t for t in targets if t.backend == backend and t.model == model]
    any_model = [t for t in targets if t.backend == backend and t.model is None]
    chosen = exact or any_model
    return chosen[0] if chosen else None


def collect_rows(
    results: Path, targets: Sequence[Target], scoring: Scoring = DEFAULT_SCORING
) -> list[Row]:
    """One row per run, labeled by its target, then a not run row for each target with no run."""
    runs = _read_runs(results, scoring)
    rows: list[tuple[int, str, Row]] = []
    covered: set[str] = set()
    for run in runs:
        target = _target_for(run, targets)
        label = target.label if target else f"{run.metrics.backend} (not in the backend list)"
        order = targets.index(target) if target else len(targets)
        if target:
            covered.add(target.label)
        rows.append((order, run.metrics.run_id or "", _row_for(label, run)))
    for order, target in enumerate(targets):
        if target.label not in covered:
            rows.append((order, "", Row.not_run(target.label)))
    return [row for _, _, row in sorted(rows, key=lambda item: item[:2])]


PAGE_HEAD = """# Evaluation results

<!-- Generated by `python -m evals.harness.table`. Do not edit by hand; CI regenerates it. -->

The table compares the approved backends on the committed hand labels. Every number is the mean
and the worst of the repeats (the worst is the lowest recall and the highest of every other
metric). A backend with no run says `not run`, never 0. The rules for reading it, and how this
page is built, are in [evals.md](evals.md#the-comparison-table). The labels are written by one
author on a small fictional bank, so these numbers are evidence for this repository only.

"""


def render_page(rows: Sequence[Row]) -> str:
    return PAGE_HEAD + render_table(rows)


def render_readme_block(rows: Sequence[Row]) -> str:
    return f"{README_START}\n{render_table(rows)}{README_END}"


def update_readme(readme: str, rows: Sequence[Row]) -> str:
    start = readme.find(README_START)
    end = readme.find(README_END)
    if start == -1 or end == -1 or end < start:
        raise TableError(f"README.md needs the markers {README_START} and {README_END}")
    return readme[:start] + render_readme_block(rows) + readme[end + len(README_END) :]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the backend comparison table.")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--backends", type=Path, default=DEFAULT_BACKENDS)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--bank", type=Path, default=DEFAULT_SCORE_BANK)
    parser.add_argument("--injection-fixtures", type=Path, default=DEFAULT_INJECTION)
    parser.add_argument("--page", type=Path, default=DEFAULT_PAGE)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = parser.parse_args(argv)
    try:
        scoring = Scoring(args.fixtures, args.bank, args.injection_fixtures)
        rows = collect_rows(args.results, load_targets(args.backends), scoring)
        page = render_page(rows)
        readme = update_readme(args.readme.read_text(encoding="utf-8"), rows)
        if args.check:
            stale = [
                path.name
                for path, text in ((args.page, page), (args.readme, readme))
                if not path.is_file() or path.read_text(encoding="utf-8") != text
            ]
            if stale:
                raise TableError(
                    f"{', '.join(stale)} is out of date; run: uv run python -m evals.harness.table"
                )
            print("the results table is current")
            return 0
        args.page.write_text(page, encoding="utf-8")
        args.readme.write_text(readme, encoding="utf-8")
    except (TableError, OSError, ValueError) as error:
        print(f"table failed: {error}", file=sys.stderr)
        return 1
    print(f"wrote {args.page.name} and the README results block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
