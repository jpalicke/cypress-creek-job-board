# ABOUTME: The gap report: each requirement with support, citations, gaps, score and provenance.
# ABOUTME: Built fail closed, and refused if any claim cites a fact that is missing or unverified.
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Importance, Posting, PostingWarning
from cypress_creek.pipeline.entail import EntailedMatch, Entailment
from cypress_creek.pipeline.extract import Dropped, ExtractionResult, ExtractionStatus
from cypress_creek.pipeline.retrieve import RequirementCandidates
from cypress_creek.providers.base import Usage
from cypress_creek.scoring.score import ScoreResult, Weights, score
from cypress_creek.scoring.support import Gate, Support
from cypress_creek.validators.citations import check_fact_exists, check_fact_verified
from cypress_creek.validators.claims import check_citation_required

TRIAGE_DISCLAIMER = "triage only, not a probability"


class ReportRefused(Exception):
    """A claim in the report cites a fact that is missing, unverified or absent."""


class ReportStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class Provenance(BaseModel):
    """Which backend and prompts made the report, for the eval harness and for reproducing a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: str
    model: str
    run_id: str
    prompt_hashes: dict[str, str]
    usage: Usage


class ReportRow(BaseModel):
    """One requirement. Every strong or partial support cites the facts it rests on.

    `rationale` is model text for display only, shown after the grounding checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    text: str
    importance: Importance
    ceiling: Support
    support: Support
    gate: Gate
    fact_ids: list[str]
    rationale: str | None
    entailment: Entailment
    not_model_checked: bool
    failure: str | None


class GapReport(BaseModel):
    """The product's output. A data structure first: text and UI are views of it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    posting_id: str
    status: ReportStatus
    incomplete_reasons: list[str]
    rows: list[ReportRow]
    gaps: list[str]
    not_assessed_count: int
    dropped: list[Dropped]
    warnings: list[PostingWarning]
    score: ScoreResult | None
    score_disclaimer: str
    rule_only_ids: list[str]
    provenance: Provenance


@dataclass(frozen=True)
class _Claim:
    text: str
    fact_ids: list[str]


def verify_report(report: GapReport, bank: Bank) -> None:
    """V4, V5 and V9 over every citation in the report. Raises ReportRefused on a failure."""
    cited = [fact_id for row in report.rows for fact_id in row.fact_ids]
    claims = [
        _Claim(row.text, row.fact_ids) for row in report.rows if row.support is not Support.NONE
    ]
    for verdict in (
        check_fact_exists(cited, bank),
        check_fact_verified(cited, bank),
        check_citation_required(claims),
    ):
        if not verdict.passed:
            raise ReportRefused(f"{verdict.validator}: {verdict.reason}: {verdict.offending}")


def _check_alignment(
    extraction: ExtractionResult,
    candidates: Sequence[RequirementCandidates],
    entailed: Sequence[EntailedMatch],
) -> None:
    """The three stage outputs must describe the same requirements in the same order."""
    expected = [requirement.id for requirement in extraction.requirements]
    if [c.requirement_id for c in candidates] != expected:
        raise ValueError(f"candidates do not line up with requirements {expected}")
    if [e.match.requirement_id for e in entailed] != expected:
        raise ValueError(f"entailment results do not line up with requirements {expected}")


def _row(
    requirement_text: str, candidate: RequirementCandidates, result: EntailedMatch
) -> ReportRow:
    """A requirement the model never weighed in on cites the candidates its ceiling rests on."""
    not_run = result.entailment is Entailment.NOT_RUN
    return ReportRow(
        requirement_id=result.match.requirement_id,
        text=requirement_text,
        importance=result.match.importance,
        ceiling=result.match.ceiling,
        support=result.match.support,
        gate=candidate.gate,
        fact_ids=list(candidate.fact_ids) if not_run else result.fact_ids,
        rationale=result.rationale,
        entailment=result.entailment,
        not_model_checked=not_run,
        failure=result.failure,
    )


def build_report(
    posting: Posting,
    extraction: ExtractionResult,
    candidates: Sequence[RequirementCandidates],
    entailed: Sequence[EntailedMatch],
    bank: Bank,
    provenance: Provenance,
    weights: Weights | None = None,
) -> GapReport:
    """Assemble the report and refuse it if any citation fails V4, V5 or V9.

    A failed extraction gives an incomplete report with no rows and no score. A failed entailment
    call for a requirement keeps the score, built from its rule ceiling, and flags the row."""
    reasons: list[str] = []
    rows: list[ReportRow] = []
    result: ScoreResult | None = None
    if extraction.status is ExtractionStatus.INCOMPLETE:
        reasons.append(f"extraction failed: {extraction.failure}")
    else:
        _check_alignment(extraction, candidates, entailed)
        rows = [
            _row(requirement.text, candidate, outcome)
            for requirement, candidate, outcome in zip(
                extraction.requirements, candidates, entailed, strict=True
            )
        ]
        result = score([outcome.match for outcome in entailed], weights)
    rule_only = [row.requirement_id for row in rows if row.not_model_checked]
    if rule_only:
        reasons.append(
            f"entailment did not run for {', '.join(rule_only)}: "
            "the score uses the rule ceiling for them"
        )
    report = GapReport(
        posting_id=posting.id,
        status=ReportStatus.INCOMPLETE if reasons else ReportStatus.COMPLETE,
        incomplete_reasons=reasons,
        rows=rows,
        gaps=[row.requirement_id for row in rows if row.support is not Support.STRONG],
        not_assessed_count=extraction.not_assessed_count,
        dropped=extraction.dropped,
        warnings=posting.warnings,
        score=result,
        score_disclaimer=TRIAGE_DISCLAIMER,
        rule_only_ids=rule_only,
        provenance=provenance,
    )
    verify_report(report, bank)
    return report
