# ABOUTME: Posting routes: add a posting by paste, link or PDF, estimate its cost, and analyze it.
# ABOUTME: The routes validate input, call the library, store the result and return typed output.
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from cypress_creek import __version__
from cypress_creek.api.backends import BackendChoiceError, check_backend_choice
from cypress_creek.api.context import Backend, BankPath, DatabasePath, backend_of
from cypress_creek.api.errors import (
    ApiError,
    ErrorCode,
    ErrorDetail,
    details_from_validation_error,
)
from cypress_creek.api.routes.facts import load_bank_or_raise
from cypress_creek.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    EstimateResponse,
    ExtractionWarning,
    PostingRequest,
    PostingResponse,
)
from cypress_creek.ingest.build import build_posting
from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.fetch import (
    BlockedByPolicy,
    Empty,
    FetchFailed,
    NeedsBrowser,
    TooLarge,
    UnsupportedContent,
)
from cypress_creek.ingest.html_text import HtmlTextError
from cypress_creek.ingest.link_posting import LinkPosting, posting_from_pdf, posting_from_url
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.ingest.pdf_text import PdfError
from cypress_creek.pipeline.extract import output_cap
from cypress_creek.pipeline.prompt import Stage, build_prompt
from cypress_creek.pipeline.report import ReportRefused
from cypress_creek.pipeline.run import analyze
from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import BudgetedProvider, BudgetExceeded, BudgetTracker
from cypress_creek.providers.budget import PlannedCall, budget_from_settings, dry_run_estimate
from cypress_creek.storage.repository import PostingStore, ReportStore, StoredVerdict

router = APIRouter()

PDF_MAGIC = b"%PDF-"
JSON_TYPE = "application/json"
PDF_TYPE = "application/pdf"


def media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


def posting_response(posting: Posting, link: LinkPosting | None = None) -> PostingResponse:
    return PostingResponse(
        id=posting.id,
        source=posting.source,
        text=posting.text,
        text_hash=posting.text_hash,
        origin_url=posting.origin_url,
        warnings=posting.warnings,
        extraction_warnings=[
            ExtractionWarning(kind=w.kind, count=w.count)
            for w in (link.extraction_warnings if link else ())
        ],
        fetch_warnings=list(link.fetch_warnings) if link else [],
        created_at=posting.created_at,
    )


def posting_from_paste(text: str) -> Posting:
    return build_posting(text, PostingSource.PASTE, Extractor(name="paste", version=__version__))


PDF_ERRORS: dict[str, tuple[int, ErrorCode]] = {
    "PdfTooLarge": (413, ErrorCode.PDF_TOO_LARGE),
    "PdfTooManyPages": (422, ErrorCode.PDF_TOO_MANY_PAGES),
    "PdfTooMuchText": (422, ErrorCode.PDF_TOO_MUCH_TEXT),
    "PdfEncrypted": (422, ErrorCode.PDF_ENCRYPTED),
    "PdfCorrupt": (422, ErrorCode.PDF_CORRUPT),
    "PdfNoText": (422, ErrorCode.PDF_NO_TEXT),
    "PdfTimeout": (422, ErrorCode.PDF_TIMEOUT),
    "PdfResourceLimit": (422, ErrorCode.PDF_RESOURCE_LIMIT),
}


def pdf_api_error(error: PdfError) -> ApiError:
    """The typed API error for a PDF failure. The message never carries the file's content."""
    status, code = PDF_ERRORS.get(type(error).__name__, (422, ErrorCode.PDF_CORRUPT))
    return ApiError(status, code)


def ingest_pdf(body: bytes, database: Path) -> PostingResponse:
    """Read an uploaded PDF in the limited child process and store its visible text."""
    try:
        link = posting_from_pdf(body, PostingSource.PDF)
    except PdfError as error:
        raise pdf_api_error(error) from None
    except EmptyPosting:
        raise ApiError(422, ErrorCode.EMPTY_POSTING) from None
    except PostingTooLong:
        raise ApiError(413, ErrorCode.POSTING_TOO_LONG) from None
    PostingStore(database).add(link.posting)
    return posting_response(link.posting, link)


def ingest(payload: PostingRequest, database: Path) -> PostingResponse:
    """Build the Posting for a paste or a link, mapping every library failure to a typed error."""
    link: LinkPosting | None = None
    try:
        if payload.source == "paste":
            assert payload.text is not None
            posting = posting_from_paste(payload.text)
        else:
            assert payload.url is not None
            link = posting_from_url(payload.url)
            posting = link.posting
    except (EmptyPosting, Empty):
        raise ApiError(422, ErrorCode.EMPTY_POSTING) from None
    except PostingTooLong:
        raise ApiError(413, ErrorCode.POSTING_TOO_LONG) from None
    except BlockedByPolicy as error:
        reason = str(getattr(error.reason_code, "value", error.reason_code))
        detail = ErrorDetail(field="reason", problem=reason)
        raise ApiError(422, ErrorCode.BLOCKED_BY_POLICY, [detail]) from None
    except NeedsBrowser:
        raise ApiError(422, ErrorCode.NEEDS_BROWSER) from None
    except UnsupportedContent:
        raise ApiError(422, ErrorCode.UNSUPPORTED_CONTENT) from None
    except TooLarge:
        raise ApiError(413, ErrorCode.CONTENT_TOO_LARGE) from None
    except HtmlTextError:
        raise ApiError(422, ErrorCode.UNREADABLE_CONTENT) from None
    except PdfError as error:
        raise pdf_api_error(error) from None
    except FetchFailed:
        raise ApiError(502, ErrorCode.FETCH_FAILED) from None
    PostingStore(database).add(posting)
    return posting_response(posting, link)


@router.post("/api/postings", status_code=201)
async def create_posting(request: Request, database: DatabasePath) -> PostingResponse:
    """A JSON paste or link, or a PDF upload as the raw body. The body size is capped earlier."""
    media = media_type(request)
    if media not in (JSON_TYPE, PDF_TYPE):
        raise ApiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE)
    body = await request.body()
    if media == PDF_TYPE:
        if not body.startswith(PDF_MAGIC):
            raise ApiError(422, ErrorCode.INVALID_PDF)
        return await run_in_threadpool(ingest_pdf, body, database)
    try:
        payload = PostingRequest.model_validate_json(body)
    except ValidationError as error:
        raise ApiError(
            422, ErrorCode.INVALID_REQUEST, details_from_validation_error(error)
        ) from None
    return await run_in_threadpool(ingest, payload, database)


def require_posting(database: Path, posting_id: str) -> Posting:
    posting = PostingStore(database).get(posting_id)
    if posting is None:
        raise ApiError(404, ErrorCode.NOT_FOUND)
    return posting


def require_backend(request: Request) -> Backend:
    backend = backend_of(request)
    if backend is None:
        raise ApiError(422, ErrorCode.UNKNOWN_BACKEND)
    return backend


BackendDep = Annotated[Backend, Depends(require_backend)]


@router.get("/api/postings/{posting_id}/estimate")
def estimate_posting(
    posting_id: str,
    backend: BackendDep,
    database: DatabasePath,
) -> EstimateResponse:
    """What the extraction call would use at most. Entailment calls follow, one per requirement."""
    posting = require_posting(database, posting_id)
    capabilities = backend.provider.capabilities
    prompt = build_prompt(Stage.EXTRACT, posting.text, [], capabilities, ExtractionOutput)
    plan = [
        PlannedCall(
            system=prompt.system,
            data_block=prompt.data_block,
            output_schema=ExtractionOutput,
            max_output_tokens=output_cap(capabilities),
        )
    ]
    try:
        cost = dry_run_estimate(backend.provider, budget_from_settings(backend.settings), plan)
    except BudgetExceeded:
        raise ApiError(409, ErrorCode.BUDGET_EXCEEDED) from None
    return EstimateResponse(
        covers="extraction",
        requests=cost.requests,
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        usd=cost.usd,
    )


@router.post("/api/postings/{posting_id}/analyze")
def analyze_posting(
    posting_id: str,
    body: AnalyzeRequest,
    backend: BackendDep,
    database: DatabasePath,
    bank_path: BankPath,
) -> AnalyzeResponse:
    posting = require_posting(database, posting_id)
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
    tracker = BudgetTracker(
        budget_from_settings(backend.settings), backend.provider.capabilities.cost_per_mtok
    )
    trace = PipelineTrace()
    try:
        report = analyze(
            posting,
            bank,
            BudgetedProvider(backend.provider, tracker),
            backend=backend.settings.provider,
            model=backend.settings.model,
            trace=trace,
        )
    except BudgetExceeded:
        raise ApiError(409, ErrorCode.BUDGET_EXCEEDED) from None
    except ReportRefused:
        raise ApiError(422, ErrorCode.REPORT_REFUSED) from None
    verdicts = [
        StoredVerdict(
            stage=record.stage,
            subject=record.subject,
            validator=record.verdict.validator,
            passed=record.verdict.passed,
            reason=record.verdict.reason,
        )
        for record in trace.validators
    ]
    report_id = ReportStore(database).add(report, verdicts)
    return AnalyzeResponse(report_id=report_id, report=report)
