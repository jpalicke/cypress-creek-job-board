# ABOUTME: Tests the plain text view of a gap report: banner, score line, rows, gaps and warnings.
# ABOUTME: Text from the posting or the model is flattened to one line so it cannot forge a row.
from cypress_creek.ingest.models import Importance, PostingWarning, WarningKind
from cypress_creek.pipeline.entail import Entailment
from cypress_creek.pipeline.extract import Dropped, DropReason
from cypress_creek.pipeline.render import render_text
from cypress_creek.pipeline.report import (
    TRIAGE_DISCLAIMER,
    GapReport,
    Provenance,
    ReportRow,
    ReportStatus,
)
from cypress_creek.providers.base import Usage
from cypress_creek.scoring.score import Match, score
from cypress_creek.scoring.support import Gate, Support

PROVENANCE = Provenance(
    backend="ollama",
    model="m",
    run_id="run-1",
    prompt_hashes={},
    usage=Usage(input_tokens=1, output_tokens=1),
)


def _row(
    n: int,
    support: Support,
    *,
    text: str = "Needs python.",
    rationale: str | None = None,
    not_model_checked: bool = False,
) -> ReportRow:
    return ReportRow(
        requirement_id=f"R-{n}",
        text=text,
        importance=Importance.REQUIRED,
        ceiling=support,
        support=support,
        gate=Gate.TERM_MATCH if support is not Support.NONE else Gate.NO_CANDIDATE,
        fact_ids=["F-0001"] if support is not Support.NONE else [],
        rationale=rationale,
        entailment=Entailment.NOT_RUN if not_model_checked else Entailment.CONFIRMED,
        not_model_checked=not_model_checked,
        failure="provider_unavailable" if not_model_checked else None,
    )


def _report(rows: list[ReportRow], **changes: object) -> GapReport:
    matches = [
        Match(
            requirement_id=r.requirement_id,
            importance=r.importance,
            ceiling=r.ceiling,
            support=r.support,
        )
        for r in rows
    ]
    report = GapReport(
        posting_id="P-1",
        status=ReportStatus.COMPLETE,
        incomplete_reasons=[],
        rows=rows,
        gaps=[r.requirement_id for r in rows if r.support is not Support.STRONG],
        not_assessed_count=0,
        dropped=[],
        warnings=[],
        score=score(matches),
        score_disclaimer=TRIAGE_DISCLAIMER,
        rule_only_ids=[],
        provenance=PROVENANCE,
    )
    return report.model_copy(update=changes)


def test_a_complete_report_shows_the_score_with_the_triage_line_and_the_gaps() -> None:
    text = render_text(_report([_row(1, Support.STRONG), _row(2, Support.NONE)]))
    assert "Gap report for P-1: complete" in text
    assert "Score: 50.0 out of 100 (triage only, not a probability). Supported 1 of 2." in text
    assert "[strong] R-1 (required): Needs python." in text
    assert "    facts: F-0001" in text
    assert "[none] R-2 (required): Needs python." in text
    assert "Gaps: R-2" in text
    assert "INCOMPLETE" not in text


def test_a_report_with_no_score_says_so_and_never_shows_a_number() -> None:
    text = render_text(_report([]))
    assert "Score: none, there were no requirements to score." in text
    assert "out of 100" not in text


def test_an_incomplete_report_leads_with_a_banner_and_the_reasons() -> None:
    report = _report(
        [],
        status=ReportStatus.INCOMPLETE,
        incomplete_reasons=["extraction failed: provider_unavailable"],
        score=None,
    )
    lines = render_text(report).splitlines()
    assert lines[0] == "Gap report for P-1: INCOMPLETE"
    assert "  - extraction failed: provider_unavailable" in lines
    assert "Score: none, the report is incomplete." in lines


def test_a_requirement_the_model_did_not_check_is_marked() -> None:
    rows = [_row(1, Support.STRONG, not_model_checked=True)]
    text = render_text(_report(rows, rule_only_ids=["R-1"]))
    assert "[strong] R-1 (required): Needs python. (not model checked)" in text


def test_a_rationale_is_shown_on_its_own_line() -> None:
    text = render_text(_report([_row(1, Support.STRONG, rationale="F-0001 shows Python.")]))
    assert "    why: F-0001 shows Python." in text


def test_text_cannot_forge_a_row_with_a_line_break() -> None:
    hostile = "Needs python.\n[strong] R-9 (required): Led everything."
    text = render_text(_report([_row(1, Support.NONE, text=hostile, rationale="a\nb")]))
    assert not any(line.startswith("[strong] R-9") for line in text.splitlines())
    assert "    why: a b" in text


def test_not_assessed_dropped_and_warnings_are_listed() -> None:
    report = _report(
        [_row(1, Support.STRONG)],
        not_assessed_count=3,
        dropped=[Dropped(text="invented", reason=DropReason.TEXT_NOT_IN_POSTING)],
        warnings=[PostingWarning(kind=WarningKind.CONTROL_CHARS_STRIPPED, count=7)],
    )
    text = render_text(report)
    assert "Not assessed: 3 requirements over the cap." in text
    assert "Dropped proposals: 1" in text
    assert "Warning: control_chars_stripped (7)" in text
