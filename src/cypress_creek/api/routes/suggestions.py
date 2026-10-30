# ABOUTME: POST /api/reports/{id}/suggestions: draft help for one requirement of a stored report.
# ABOUTME: Never drafts without a verified supporting fact; every sentence carries its verdicts.
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter
from pydantic import Field

from cypress_creek.api.backends import BackendChoiceError, check_backend_choice
from cypress_creek.api.context import BankPath, DatabasePath
from cypress_creek.api.errors import ApiError, ErrorCode
from cypress_creek.api.routes.facts import load_bank_or_raise
from cypress_creek.api.routes.postings import BackendDep
from cypress_creek.api.schemas import ApiModel
from cypress_creek.pipeline.draft import Draft, DraftStatus, draft
from cypress_creek.pipeline.retrieve import RequirementCandidates
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import BudgetExceeded
from cypress_creek.providers.budget import BudgetedProvider, BudgetTracker, budget_from_settings
from cypress_creek.storage.repository import ReportStore

router = APIRouter()


class SuggestionRequest(ApiModel):
    requirement_id: Annotated[str, Field(pattern=r"^R-\d+$", max_length=20)]
    backend: Annotated[str, Field(min_length=1, max_length=100)]
    confirm_hosted: bool = False


class VerdictOut(ApiModel):
    validator: str
    passed: bool
    reason: str


class SentenceOut(ApiModel):
    text: str
    fact_ids: list[str]
    passed: bool
    verdicts: list[VerdictOut]


class CitedFact(ApiModel):
    id: str
    claim: str


class SuggestionResponse(ApiModel):
    requirement_id: str
    requirement_text: str
    status: DraftStatus
    failure: str | None
    needs_human_review: bool
    sentences: list[SentenceOut]
    facts: list[CitedFact]


@dataclass(frozen=True)
class _Target:
    id: str
    text: str


def _response(result: Draft, claims: dict[str, str]) -> SuggestionResponse:
    cited = sorted({fid for sentence in result.sentences for fid in sentence.fact_ids})
    return SuggestionResponse(
        requirement_id=result.requirement_id,
        requirement_text=result.requirement_text,
        status=result.status,
        failure=result.failure,
        needs_human_review=result.needs_human_review,
        sentences=[
            SentenceOut(
                text=sentence.text,
                fact_ids=sentence.fact_ids,
                passed=sentence.passed,
                verdicts=[
                    VerdictOut(validator=v.validator, passed=v.passed, reason=v.reason)
                    for v in sentence.verdicts
                ],
            )
            for sentence in result.sentences
        ],
        facts=[CitedFact(id=fid, claim=claims[fid]) for fid in cited if fid in claims],
    )


@router.post("/api/reports/{report_id}/suggestions")
def suggest(
    report_id: str,
    body: SuggestionRequest,
    backend: BackendDep,
    database: DatabasePath,
    bank_path: BankPath,
) -> SuggestionResponse:
    stored = ReportStore(database).get(report_id)
    if stored is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    row = next((r for r in stored.report.rows if r.requirement_id == body.requirement_id), None)
    if row is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    try:
        check_backend_choice(
            body.backend,
            body.confirm_hosted,
            configured=backend.settings.provider,
            capabilities=backend.provider.capabilities,
        )
    except BackendChoiceError as error:
        raise ApiError(422, ErrorCode(error.code)) from None
    bank = load_bank_or_raise(bank_path)
    candidates = RequirementCandidates(
        requirement_id=row.requirement_id,
        fact_ids=list(row.fact_ids),
        dropped_count=0,
        support=row.support,
        gate=row.gate,
    )
    tracker = BudgetTracker(
        budget_from_settings(backend.settings), backend.provider.capabilities.cost_per_mtok
    )
    try:
        result = draft(
            _Target(row.requirement_id, row.text),
            candidates,
            bank,
            BudgetedProvider(backend.provider, tracker),
            trace=PipelineTrace(),
        )
    except BudgetExceeded:
        raise ApiError(409, ErrorCode.BUDGET_EXCEEDED) from None
    return _response(result, {fact.id: fact.claim for fact in bank.facts})
