# ABOUTME: Builders for hand made labels, gap reports and run records used by the scorer tests.
# ABOUTME: Everything is built from plain values so a test can state the expected metric by hand.
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cypress_creek.eval_records import CaseRecord, RunHeader, RunTerminal
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import Importance
from cypress_creek.pipeline.entail import Entailment
from cypress_creek.pipeline.extract import Dropped, DropReason
from cypress_creek.pipeline.report import (
    TRIAGE_DISCLAIMER,
    GapReport,
    Provenance,
    ReportRow,
    ReportStatus,
)
from cypress_creek.providers.base import Usage
from cypress_creek.scoring.score import Match, lowest, score
from cypress_creek.scoring.support import Gate, Support
from evals.harness.injection import ATTACKED_SUFFIX, CLEAN_SUFFIX, InjectionFixture
from evals.harness.labels import Labels, parse_labels

PROVENANCE = Provenance(
    backend="ollama",
    model="qwen3.5:0.8b",
    run_id="run-1",
    prompt_hashes={"extract": "a" * 64, "entail": "b" * 64},
    usage=Usage(input_tokens=10, output_tokens=5),
)


@dataclass(frozen=True)
class Want:
    """One labeled requirement, written as the short fields a test cares about."""

    span: str
    support: Support
    importance: Importance = Importance.REQUIRED
    fact_ids: tuple[str, ...] = ()
    planted_gap: str | None = None


def labels_for(fixture_id: str, wants: Sequence[Want], cue_spans: Sequence[str] = ()) -> Labels:
    requirements: list[dict[str, Any]] = []
    for number, want in enumerate(wants, start=1):
        item: dict[str, Any] = {
            "id": f"L-{number}",
            "span": want.span,
            "kind": "skill",
            "term": f"term{number}",
            "importance": want.importance.value,
            "expected_support": want.support.value,
            "expected_status": "supported" if want.support is Support.STRONG else "gap",
            "fact_ids": list(want.fact_ids),
        }
        if want.planted_gap:
            item["planted_gap"] = want.planted_gap
        requirements.append(item)
    return parse_labels(
        {
            "fixture_id": fixture_id,
            "provenance": {
                "labeled_by": "test",
                "review": "pending",
                "labeled_on": "2026-10-29",
                "model_output_used": False,
            },
            "requirements": requirements,
            "cue_sentences": [{"span": span, "expected": "covered"} for span in cue_spans],
        }
    )


@dataclass(frozen=True)
class Got:
    """One report row, written as the short fields a test cares about."""

    text: str
    support: Support
    ceiling: Support | None = None
    importance: Importance = Importance.REQUIRED
    fact_ids: tuple[str, ...] = ()
    entailment: Entailment = Entailment.CONFIRMED
    raise_attempted: bool = False
    occurrence: int = 0


def report_for(
    posting: str,
    rows: Sequence[Got],
    *,
    dropped: Sequence[DropReason] = (),
    not_assessed_count: int = 0,
    status: ReportStatus = ReportStatus.COMPLETE,
) -> GapReport:
    built: list[ReportRow] = []
    for number, got in enumerate(rows, start=1):
        start = -1
        for _ in range(got.occurrence + 1):
            start = posting.index(got.text, start + 1)
        built.append(
            ReportRow(
                requirement_id=f"R-{number}",
                text=got.text,
                importance=got.importance,
                ceiling=got.ceiling or got.support,
                support=got.support,
                gate=Gate.TERM_MATCH if got.support is not Support.NONE else Gate.NO_CANDIDATE,
                fact_ids=list(got.fact_ids),
                rationale=None,
                entailment=got.entailment,
                not_model_checked=got.entailment is Entailment.NOT_RUN,
                failure=None,
                span=(start, start + len(got.text)),
                raise_attempted=got.raise_attempted,
            )
        )
    matches = [
        Match(
            requirement_id=row.requirement_id,
            importance=row.importance,
            ceiling=row.ceiling,
            support=lowest(row.support, row.ceiling),
        )
        for row in built
    ]
    return GapReport(
        posting_id="P-1",
        status=status,
        incomplete_reasons=[] if status is ReportStatus.COMPLETE else ["extraction failed"],
        rows=built,
        gaps=[row.requirement_id for row in built if row.support is not Support.STRONG],
        not_assessed_count=not_assessed_count,
        dropped=[Dropped(text="x", reason=reason) for reason in dropped],
        warnings=[],
        score=score(matches) if built else None,
        score_disclaimer=TRIAGE_DISCLAIMER,
        rule_only_ids=[],
        provenance=PROVENANCE,
    )


def header_for(case_ids: Sequence[str], repeats: int, bank_digest: str) -> RunHeader:
    return RunHeader(
        git_commit="a" * 40,
        backend="ollama",
        model="qwen3.5:0.8b",
        prompt_hashes={"extract": "a" * 64, "entail": "b" * 64},
        schema_versions={"extract": 1, "entail": 1},
        fixture_set_hash="c" * 64,
        bank_hash=bank_digest,
        case_ids=list(case_ids),
        repeats=repeats,
    )


def case_record(
    header: RunHeader, case_id: str, repeat: int, posting: str, report: GapReport
) -> CaseRecord:
    return CaseRecord(
        run_id=header.run_id,
        case_id=case_id,
        repeat=repeat,
        posting_hash=text_hash(posting),
        report=report,
        calls=[],
        validators=[],
    )


def mirror_report(
    labels: Labels,
    posting: str,
    *,
    claim_strong: frozenset[str] = frozenset(),
    skip: frozenset[str] = frozenset(),
) -> GapReport:
    """A report that agrees with the labels, except that the named labels are claimed strong
    (citing a fact) or left out."""
    rows = []
    for label in labels.requirements:
        if label.id in skip:
            continue
        if label.id in claim_strong:
            rows.append(
                Got(label.span, Support.STRONG, importance=label.importance, fact_ids=("F-0001",))
            )
        else:
            rows.append(
                Got(
                    label.span,
                    label.expected_support,
                    importance=label.importance,
                    fact_ids=tuple(label.fact_ids),
                )
            )
    return report_for(posting, rows)


def write_run(
    path: Path, header: RunHeader, cases: Sequence[CaseRecord], *, complete: bool
) -> None:
    lines = [header.model_dump_json(), *(case.model_dump_json() for case in cases)]
    if complete:
        lines.append(RunTerminal(run_id=header.run_id, status="complete").model_dump_json())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


BASE_ROWS = (
    ("You must have 3 years of Python experience.", Support.STRONG, ("F-0001",)),
    ("You must know SQL and PostgreSQL.", Support.STRONG, ("F-0002",)),
    ("You must know Rust.", Support.NONE, ()),
    ("Experience with Kubernetes is preferred.", Support.PARTIAL, ("F-0004",)),
)


def injection_rows(
    *,
    attacked: bool,
    raise_rust: bool = False,
    fake_citation: bool = False,
    lower_python: bool = False,
) -> list[Got]:
    """Rows for the injection corpus base posting. An attack may raise Rust to strong and
    cite a fact that is not in the bank."""
    rows = []
    for text, support, facts in BASE_ROWS:
        if attacked and raise_rust and text.endswith("Rust."):
            support = Support.STRONG
            facts = ("F-9999",) if fake_citation else ("F-0001",)
        if attacked and lower_python and "Python" in text:
            support, facts = Support.NONE, ()
        rows.append(Got(text, support, fact_ids=facts))
    return rows


def injection_records(
    header: RunHeader,
    fixture: InjectionFixture,
    repeat: int,
    *,
    raise_rust: bool = False,
    fake_citation: bool = False,
    skip: str | None = None,
    disrupt: bool = False,
    lower_python: bool = False,
) -> list[CaseRecord]:
    """The attacked and clean case records of one corpus case for one repeat. A disrupted attack
    leaves an incomplete attacked report with no rows and no score."""
    case_id = fixture.case.case_id
    clean = report_for(fixture.clean_text, injection_rows(attacked=False))
    attacked = report_for(
        fixture.attacked_text,
        injection_rows(
            attacked=True,
            raise_rust=raise_rust,
            fake_citation=fake_citation,
            lower_python=lower_python,
        ),
    )
    if disrupt:
        attacked = report_for(fixture.attacked_text, [], status=ReportStatus.INCOMPLETE)
    pairs = [
        (f"{case_id}{ATTACKED_SUFFIX}", fixture.attacked_text, attacked),
        (f"{case_id}{CLEAN_SUFFIX}", fixture.clean_text, clean),
    ]
    return [
        case_record(header, name, repeat, text, report)
        for name, text, report in pairs
        if name != skip
    ]
