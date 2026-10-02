# ABOUTME: Plain text view of a gap report for the command line and the API.
# ABOUTME: Posting and model text is flattened to one line so it cannot forge a row or a banner.
from cypress_creek.pipeline.report import GapReport, ReportRow, ReportStatus


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _score_line(report: GapReport) -> str:
    if report.score is None:
        return "Score: none, the report is incomplete."
    if report.score.score is None:
        return "Score: none, there were no requirements to score."
    return (
        f"Score: {report.score.score:.1f} out of 100 ({report.score_disclaimer}). "
        f"Supported {report.score.supported} of {report.score.total}."
    )


def _row_lines(row: ReportRow) -> list[str]:
    marker = " (not model checked)" if row.not_model_checked else ""
    lines = [
        f"[{row.support.value}] {row.requirement_id} ({row.importance.value}): "
        f"{_one_line(row.text)}{marker}"
    ]
    if row.fact_ids:
        lines.append(f"    facts: {', '.join(row.fact_ids)}")
    if row.rationale:
        lines.append(f"    why: {_one_line(row.rationale)}")
    return lines


def render_text(report: GapReport) -> str:
    """One view of the report. The data is the report, this only lays it out."""
    incomplete = report.status is ReportStatus.INCOMPLETE
    lines = [f"Gap report for {report.posting_id}: {'INCOMPLETE' if incomplete else 'complete'}"]
    lines += [f"  - {reason}" for reason in report.incomplete_reasons]
    lines.append(_score_line(report))
    for row in report.rows:
        lines += _row_lines(row)
    if report.gaps:
        lines.append(f"Gaps: {', '.join(report.gaps)}")
    if report.not_assessed_count:
        lines.append(f"Not assessed: {report.not_assessed_count} requirements over the cap.")
    if report.dropped:
        lines.append(f"Dropped proposals: {len(report.dropped)}")
    lines += [f"Warning: {warning.kind.value} ({warning.count})" for warning in report.warnings]
    return "\n".join(lines)
