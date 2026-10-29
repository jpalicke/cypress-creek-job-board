# ABOUTME: The E1 to E4 eval metrics: counts per case, rates per repeat, mean and worst per run.
# ABOUTME: Pure functions over hand labels and recorded reports, so a score is reproducible.
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Bank
from cypress_creek.pipeline.entail import Entailment
from cypress_creek.pipeline.extract import DropReason
from cypress_creek.pipeline.report import GapReport, ReportRow
from cypress_creek.scoring.support import Support
from evals.harness.labels import LabeledRequirement, Labels, Status

# A row matches a label when the overlap of their posting spans is at least half of their union.
MIN_OVERLAP_OVER_UNION = 0.5
SHOWN_TEXT = 80
_RANK = {Support.NONE: 0, Support.PARTIAL: 1, Support.STRONG: 2}
INVALID_PROPOSALS = (DropReason.TEXT_NOT_IN_POSTING, DropReason.INVALID_FIELD)


class ScoreError(Exception):
    """A run cannot be scored: a report lacks the data the scorer needs."""


class Direction(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"


@dataclass(frozen=True)
class Metric:
    name: str
    experiment: str
    direction: Direction
    is_rate: bool
    meaning: str


METRICS = (
    Metric(
        "span_validity_rate", "E1", Direction.HIGHER, True, "proposals whose text is in the posting"
    ),
    Metric(
        "requirement_recall", "E1", Direction.HIGHER, True, "labeled requirements the run extracted"
    ),
    Metric(
        "requirement_precision",
        "E1",
        Direction.HIGHER,
        True,
        "extracted requirements that are labeled",
    ),
    Metric(
        "importance_agreement",
        "E1",
        Direction.HIGHER,
        True,
        "matched requirements with the labeled importance",
    ),
    Metric("dedupe_hits", "E1", Direction.LOWER, False, "proposals dropped as duplicate terms"),
    Metric(
        "cap_hits", "E1", Direction.LOWER, False, "proposals left unassessed by the requirement cap"
    ),
    Metric(
        "downgrade_accuracy",
        "E2",
        Direction.HIGHER,
        True,
        "entailed rows that downgraded exactly when the label says",
    ),
    Metric(
        "tag_gate_disagreement_rate",
        "E2",
        Direction.LOWER,
        True,
        "entailed rows where the model lowered the rule ceiling",
    ),
    Metric(
        "attempted_raises",
        "E2",
        Direction.LOWER,
        False,
        "model verdicts above the rule ceiling, before the clamp",
    ),
    Metric(
        "raises_after_clamp",
        "E2",
        Direction.LOWER,
        False,
        "reported rows whose support is above their ceiling",
    ),
    Metric(
        "grounding_violations_per_100",
        "E3",
        Direction.LOWER,
        False,
        "fabricated, unverified and uncited claims per 100 reports",
    ),
    Metric(
        "fabricated_ids", "E3", Direction.LOWER, False, "cited fact ids that are not in the bank"
    ),
    Metric(
        "unverified_citations", "E3", Direction.LOWER, False, "cited facts that are not verified"
    ),
    Metric(
        "uncited_claims",
        "E3",
        Direction.LOWER,
        False,
        "rows with partial or strong support and no citation",
    ),
    Metric(
        "gap_recall", "E4", Direction.HIGHER, True, "extracted planted gaps not reported as strong"
    ),
    Metric(
        "false_support_rate",
        "E4",
        Direction.LOWER,
        True,
        "matched rows with more support than the label",
    ),
)


class MissedGap(BaseModel):
    """A planted gap that the run reported as strong, with the facts it cited."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    repeat: int
    label_id: str
    planted_gap: str
    claimed: Support
    fact_ids: list[str]


class Counts(BaseModel):
    """Everything the rates are built from. Counts add across cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reports: int = 0
    labeled: int = 0
    rows: int = 0
    matched: int = 0
    importance_agree: int = 0
    proposals: int = 0
    invalid_proposals: int = 0
    dedupe_hits: int = 0
    cap_hits: int = 0
    entailed: int = 0
    entailed_downgraded: int = 0
    downgrade_checked: int = 0
    downgrade_correct: int = 0
    attempted_raises: int = 0
    raises_after_clamp: int = 0
    fabricated_ids: int = 0
    unverified_citations: int = 0
    uncited_claims: int = 0
    planted_matched: int = 0
    planted_caught: int = 0
    planted_not_extracted: int = 0
    false_support: int = 0


class CaseScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    repeat: int
    counts: Counts
    missed: list[MissedGap]
    mismatches: list[str]


def _overlap(first: tuple[int, int], second: tuple[int, int]) -> int:
    return max(0, min(first[1], second[1]) - max(first[0], second[0]))


def _occurrences(text: str, span: str) -> list[tuple[int, int]]:
    found = []
    start = text.find(span)
    while start != -1:
        found.append((start, start + len(span)))
        start = text.find(span, start + 1)
    return found


def _row_span(row: ReportRow) -> tuple[int, int]:
    if row.span is None:
        raise ScoreError(f"row {row.requirement_id} has no span; the report predates the scorer")
    return row.span


def match_rows(labels: Labels, posting: str, report: GapReport) -> dict[int, int]:
    """One to one matches {label index: row index}, largest overlap first, ties by position."""
    candidates: list[tuple[int, int, int]] = []
    for row_index, row in enumerate(report.rows):
        row_span = _row_span(row)
        for label_index, label in enumerate(labels.requirements):
            best = max(
                (_overlap(span, row_span) for span in _occurrences(posting, label.span)),
                default=0,
            )
            union = len(label.span) + (row_span[1] - row_span[0]) - best
            if best > 0 and best >= MIN_OVERLAP_OVER_UNION * union:
                candidates.append((-best, label_index, row_index))
    matched: dict[int, int] = {}
    used_rows: set[int] = set()
    for _, label_index, row_index in sorted(candidates):
        if label_index not in matched and row_index not in used_rows:
            matched[label_index] = row_index
            used_rows.add(row_index)
    return matched


def _shown(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SHOWN_TEXT else flat[: SHOWN_TEXT - 3] + "..."


def _grounding(row: ReportRow, bank: Bank, where: str, lines: list[str]) -> tuple[int, int, int]:
    facts = {fact.id: fact for fact in bank.facts}
    fabricated = unverified = 0
    for fact_id in row.fact_ids:
        fact = facts.get(fact_id)
        if fact is None:
            fabricated += 1
            lines.append(f"{where} {row.requirement_id}: cites {fact_id}, which is not in the bank")
        elif not fact.is_verified:
            unverified += 1
            lines.append(f"{where} {row.requirement_id}: cites {fact_id}, which is not verified")
    uncited = int(row.support is not Support.NONE and not row.fact_ids)
    if uncited:
        lines.append(f"{where} {row.requirement_id}: claims {row.support.value} with no citation")
    return fabricated, unverified, uncited


def _compare(
    label: LabeledRequirement, row: ReportRow, case_id: str, repeat: int
) -> tuple[Counts, list[str], MissedGap | None]:
    where = f"{case_id} repeat {repeat}"
    lines: list[str] = []
    entailed = row.entailment in (Entailment.CONFIRMED, Entailment.DOWNGRADED)
    should = _RANK[label.expected_support] < _RANK[row.ceiling]
    did = _RANK[row.support] < _RANK[row.ceiling]
    over = _RANK[row.support] > _RANK[label.expected_support]
    if label.importance is not row.importance:
        lines.append(
            f"{where} {label.id}: importance labeled {label.importance.value}, "
            f"got {row.importance.value}"
        )
    if over:
        lines.append(
            f"{where} {label.id}: claims {row.support.value}, "
            f"labeled {label.expected_support.value}"
        )
    elif row.support is not label.expected_support:
        lines.append(
            f"{where} {label.id}: reports {row.support.value}, "
            f"labeled {label.expected_support.value}"
        )
    if entailed and did != should:
        lines.append(
            f"{where} {label.id}: entailment {'downgraded' if did else 'kept'} the ceiling "
            f"{row.ceiling.value}, label expects {label.expected_support.value}"
        )
    caught = row.support is not Support.STRONG
    planted = label.planted_gap is not None and label.expected_status is Status.GAP
    missed = None
    if planted and not caught and label.planted_gap is not None:
        missed = MissedGap(
            case_id=case_id,
            repeat=repeat,
            label_id=label.id,
            planted_gap=label.planted_gap,
            claimed=row.support,
            fact_ids=list(row.fact_ids),
        )
    counts = Counts(
        matched=1,
        importance_agree=int(label.importance is row.importance),
        entailed=int(entailed),
        entailed_downgraded=int(row.entailment is Entailment.DOWNGRADED),
        downgrade_checked=int(entailed),
        downgrade_correct=int(entailed and did == should),
        planted_matched=int(planted),
        planted_caught=int(planted and caught),
        false_support=int(over),
    )
    return counts, lines, missed


def _add(first: Counts, second: Counts) -> Counts:
    merged = {name: getattr(first, name) + getattr(second, name) for name in Counts.model_fields}
    return Counts(**merged)


def score_case(
    labels: Labels,
    posting: str,
    report: GapReport,
    bank: Bank,
    *,
    case_id: str = "",
    repeat: int = 0,
) -> CaseScore:
    """Compare one report with its hand labels and count every kind of agreement and error."""
    where = f"{case_id} repeat {repeat}"
    matched = match_rows(labels, posting, report)
    matched_rows = set(matched.values())
    lines: list[str] = []
    missed: list[MissedGap] = []
    totals = Counts(
        reports=1,
        labeled=len(labels.requirements),
        rows=len(report.rows),
        proposals=len(report.rows) + len(report.dropped) + report.not_assessed_count,
        invalid_proposals=sum(1 for item in report.dropped if item.reason in INVALID_PROPOSALS),
        dedupe_hits=sum(1 for item in report.dropped if item.reason is DropReason.DUPLICATE_TERM),
        cap_hits=report.not_assessed_count,
        attempted_raises=sum(1 for row in report.rows if row.raise_attempted),
        raises_after_clamp=sum(1 for row in report.rows if _RANK[row.support] > _RANK[row.ceiling]),
    )
    for label_index, label in enumerate(labels.requirements):
        if label_index not in matched:
            planted = label.planted_gap is not None
            totals = _add(totals, Counts(planted_not_extracted=int(planted)))
            lines.append(f"{where} {label.id}: not extracted: {_shown(label.span)}")
            continue
        counts, found, gap = _compare(label, report.rows[matched[label_index]], case_id, repeat)
        totals = _add(totals, counts)
        lines += found
        if gap is not None:
            missed.append(gap)
    for row_index, row in enumerate(report.rows):
        if row_index not in matched_rows:
            lines.append(f"{where} {row.requirement_id}: extra, not labeled: {_shown(row.text)}")
        if row.raise_attempted:
            lines.append(f"{where} {row.requirement_id}: model attempted to raise support")
        fabricated, unverified, uncited = _grounding(row, bank, where, lines)
        totals = _add(
            totals,
            Counts(
                fabricated_ids=fabricated, unverified_citations=unverified, uncited_claims=uncited
            ),
        )
    return CaseScore(case_id=case_id, repeat=repeat, counts=totals, missed=missed, mismatches=lines)


def grounding_violations(report: GapReport, bank: Bank) -> int:
    """Fabricated ids, unverified citations and uncited claims over every row of a report."""
    total = 0
    for row in report.rows:
        total += sum(_grounding(row, bank, "", []))
    return total


def pool(cases: Sequence[CaseScore]) -> Counts:
    """Add the counts of every case in one repeat."""
    total = Counts()
    for case in cases:
        total = _add(total, case.counts)
    return total


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def repeat_values(counts: Counts) -> dict[str, float | None]:
    """The metric values of one repeat. None means there was nothing to measure."""
    ran = counts.reports > 0

    def count(value: int) -> float | None:
        return float(value) if ran else None

    return {
        "span_validity_rate": _ratio(counts.proposals - counts.invalid_proposals, counts.proposals),
        "requirement_recall": _ratio(counts.matched, counts.labeled),
        "requirement_precision": _ratio(counts.matched, counts.rows),
        "importance_agreement": _ratio(counts.importance_agree, counts.matched),
        "dedupe_hits": count(counts.dedupe_hits),
        "cap_hits": count(counts.cap_hits),
        "downgrade_accuracy": _ratio(counts.downgrade_correct, counts.downgrade_checked),
        "tag_gate_disagreement_rate": _ratio(counts.entailed_downgraded, counts.entailed),
        "attempted_raises": count(counts.attempted_raises),
        "raises_after_clamp": count(counts.raises_after_clamp),
        "grounding_violations_per_100": (
            100
            * (counts.fabricated_ids + counts.unverified_citations + counts.uncited_claims)
            / counts.reports
            if ran
            else None
        ),
        "fabricated_ids": count(counts.fabricated_ids),
        "unverified_citations": count(counts.unverified_citations),
        "uncited_claims": count(counts.uncited_claims),
        "gap_recall": _ratio(counts.planted_caught, counts.planted_matched),
        "false_support_rate": _ratio(counts.false_support, counts.matched),
    }


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment: str
    direction: Direction
    meaning: str
    status: Literal["scored", "not_run"]
    runs: list[float]
    mean: float | None
    worst: float | None


def aggregate(
    per_repeat: Sequence[Mapping[str, float | None]], metrics: Sequence[Metric] = METRICS
) -> dict[str, MetricValue]:
    """Mean and worst of each metric over the repeats that measured it. No runs is not run."""
    result: dict[str, MetricValue] = {}
    for metric in metrics:
        runs = [value for values in per_repeat if (value := values.get(metric.name)) is not None]
        worst = None
        if runs:
            worst = min(runs) if metric.direction is Direction.HIGHER else max(runs)
        result[metric.name] = MetricValue(
            experiment=metric.experiment,
            direction=metric.direction,
            meaning=metric.meaning,
            status="scored" if runs else "not_run",
            runs=runs,
            mean=math.fsum(runs) / len(runs) if runs else None,
            worst=worst,
        )
    return result
