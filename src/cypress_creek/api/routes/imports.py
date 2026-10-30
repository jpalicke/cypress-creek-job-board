# ABOUTME: Resume import routes: propose facts from a resume, list pending ones, approve, reject.
# ABOUTME: Nothing here verifies a fact; approving writes an unverified, local only fact.
from typing import Annotated

from fastapi import APIRouter, Request
from fastapi import Path as RoutePath
from fastapi.concurrency import run_in_threadpool
from pydantic import Field, ValidationError

from cypress_creek.api.backends import BackendChoiceError, check_backend_choice
from cypress_creek.api.context import BankPath, DatabasePath, backend_of
from cypress_creek.api.errors import (
    ApiError,
    ErrorCode,
    details_from_validation_error,
)
from cypress_creek.api.routes.postings import JSON_TYPE, PDF_TYPE, media_type, pdf_api_error
from cypress_creek.api.schemas import ApiModel
from cypress_creek.facts.errors import BankLoadError, FactValidationError
from cypress_creek.facts.models import Evidence, EvidenceType, Fact, Level, Tag
from cypress_creek.facts.store import BankStore, FactDraft
from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.normalize import normalize
from cypress_creek.ingest.pdf_text import PdfError, extract_pdf_text
from cypress_creek.pipeline.resume_import import propose_candidates
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import BudgetExceeded
from cypress_creek.providers.budget import BudgetedProvider, BudgetTracker, budget_from_settings
from cypress_creek.storage.candidates import (
    CandidateNotPending,
    CandidateStore,
    State,
    StoredCandidate,
)

router = APIRouter()

MAX_RESUME_CHARS = 100_000
CandidateId = Annotated[str, RoutePath(pattern=r"^C-[0-9a-f]{16}$")]


class ResumeRequest(ApiModel):
    text: Annotated[str, Field(min_length=1, max_length=MAX_RESUME_CHARS)]
    backend: Annotated[str, Field(min_length=1, max_length=100)]
    confirm_hosted: bool = False


class CandidateOut(ApiModel):
    id: str
    claim: str
    kind: str
    tags: list[str]
    source: str
    state: str


class ExtractionWarningOut(ApiModel):
    kind: str
    count: int


class ImportResponse(ApiModel):
    resume_hash: str
    status: str
    failure: str | None
    backend: str
    hosted: bool
    candidates: list[CandidateOut]
    dropped: dict[str, int]
    extraction_warnings: list[ExtractionWarningOut]


class CandidatesResponse(ApiModel):
    candidates: list[CandidateOut]


class ApprovedResponse(ApiModel):
    candidate: CandidateOut
    fact: Fact


def _out(candidate: StoredCandidate) -> CandidateOut:
    return CandidateOut(
        id=candidate.id,
        claim=candidate.claim,
        kind=candidate.kind.value,
        tags=candidate.tags,
        source=candidate.source,
        state=candidate.state,
    )


def _import(
    resume_text: str,
    backend_name: str,
    confirm_hosted: bool,
    request: Request,
    database_path: DatabasePath,
    bank_path: BankPath,
    warnings: list[ExtractionWarningOut],
) -> ImportResponse:
    backend = backend_of(request)
    if backend is None:
        raise ApiError(422, ErrorCode.UNKNOWN_BACKEND)
    try:
        check_backend_choice(
            backend_name,
            confirm_hosted,
            configured=backend.settings.provider,
            capabilities=backend.provider.capabilities,
        )
    except BackendChoiceError as error:
        raise ApiError(422, ErrorCode(error.code)) from None
    try:
        text, _ = normalize(resume_text)
        known = [fact.claim for fact in BankStore(bank_path).facts()]
    except EmptyPosting:
        raise ApiError(422, ErrorCode.EMPTY_POSTING) from None
    except PostingTooLong:
        raise ApiError(413, ErrorCode.POSTING_TOO_LONG) from None
    except (BankLoadError, FactValidationError):
        raise ApiError(422, ErrorCode.BANK_INVALID) from None
    tracker = BudgetTracker(
        budget_from_settings(backend.settings), backend.provider.capabilities.cost_per_mtok
    )
    try:
        result = propose_candidates(
            text,
            BudgetedProvider(backend.provider, tracker),
            known,
            trace=PipelineTrace(),
        )
    except BudgetExceeded:
        raise ApiError(409, ErrorCode.BUDGET_EXCEEDED) from None
    resume_hash = text_hash(text)
    stored = CandidateStore(database_path).add_all(resume_hash, result.candidates)
    dropped = dict(result.dropped)
    if len(stored) < len(result.candidates):
        dropped["already_pending"] = len(result.candidates) - len(stored)
    return ImportResponse(
        resume_hash=resume_hash,
        status=result.status,
        failure=result.failure,
        backend=backend.settings.provider,
        hosted=not backend.provider.capabilities.local,
        candidates=[_out(candidate) for candidate in stored],
        dropped=dropped,
        extraction_warnings=warnings,
    )


@router.post("/api/import/resume")
async def import_resume(
    request: Request,
    database_path: DatabasePath,
    bank_path: BankPath,
    backend: str | None = None,
    confirm_hosted: bool = False,
) -> ImportResponse:
    """A resume as JSON text, or a PDF as the raw body with the backend in the query string.

    The resume is read, normalized, sent to the model and forgotten: only its hash is kept."""
    media = media_type(request)
    body = await request.body()
    if media == PDF_TYPE:
        if backend is None:
            raise ApiError(422, ErrorCode.INVALID_REQUEST)
        try:
            extracted = await run_in_threadpool(extract_pdf_text, body)
        except PdfError as error:
            raise pdf_api_error(error) from None
        dropped_hidden = [
            ExtractionWarningOut(kind=w.kind, count=w.count) for w in extracted.warnings
        ]
        return await run_in_threadpool(
            _import,
            extracted.text,
            backend,
            confirm_hosted,
            request,
            database_path,
            bank_path,
            dropped_hidden,
        )
    if media != JSON_TYPE:
        raise ApiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE)
    try:
        payload = ResumeRequest.model_validate_json(body)
    except ValidationError as error:
        raise ApiError(
            422, ErrorCode.INVALID_REQUEST, details_from_validation_error(error)
        ) from None
    return await run_in_threadpool(
        _import,
        payload.text,
        payload.backend,
        payload.confirm_hosted,
        request,
        database_path,
        bank_path,
        [],
    )


@router.get("/api/import/candidates")
def list_candidates(
    database_path: DatabasePath, state: State | None = "pending"
) -> CandidatesResponse:
    return CandidatesResponse(
        candidates=[_out(c) for c in CandidateStore(database_path).list(state)]
    )


@router.post("/api/import/candidates/{candidate_id}/approve")
def approve_candidate(
    candidate_id: CandidateId, database_path: DatabasePath, bank_path: BankPath
) -> ApprovedResponse:
    """Write one unverified, local only fact. Verifying it stays a separate step by a person."""
    store = CandidateStore(database_path)
    candidate = store.get(candidate_id)
    if candidate is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    try:
        store.decide(candidate_id, "approved")
    except CandidateNotPending:
        raise ApiError(409, ErrorCode.CANDIDATE_NOT_PENDING) from None
    draft = FactDraft(
        claim=candidate.claim,
        kind=candidate.kind,
        tags=[Tag(name=name, level=Level.FAMILIAR) for name in candidate.tags],
        evidence=Evidence(
            type=EvidenceType.SELF_ATTESTED,
            pointer=f"resume import {candidate.resume_hash[:12]}",
        ),
    )
    try:
        fact = BankStore(bank_path).add(draft)
    except (FactValidationError, BankLoadError, ValueError):
        store.reopen(candidate_id)
        raise ApiError(422, ErrorCode.INVALID_REQUEST) from None
    store.attach_fact(candidate_id, fact.id)
    approved = store.get(candidate_id)
    assert approved is not None
    return ApprovedResponse(candidate=_out(approved), fact=fact)


@router.post("/api/import/candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: CandidateId, database_path: DatabasePath) -> CandidateOut:
    store = CandidateStore(database_path)
    if store.get(candidate_id) is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    try:
        store.decide(candidate_id, "rejected")
    except CandidateNotPending:
        raise ApiError(409, ErrorCode.CANDIDATE_NOT_PENDING) from None
    rejected = store.get(candidate_id)
    assert rejected is not None
    return _out(rejected)
