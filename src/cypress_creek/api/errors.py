# ABOUTME: The one typed error shape every API failure uses, with stable codes and fixed messages.
# ABOUTME: Messages never carry secrets, stack traces, submitted values or remote content.
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class ErrorCode(StrEnum):
    HOST_NOT_ALLOWED = "host_not_allowed"
    CSRF_TOKEN_INVALID = "csrf_token_invalid"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    INVALID_REQUEST = "invalid_request"
    HTTP_ERROR = "http_error"
    INTERNAL_ERROR = "internal_error"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    EMPTY_POSTING = "empty_posting"
    POSTING_TOO_LONG = "posting_too_long"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    FETCH_FAILED = "fetch_failed"
    NEEDS_BROWSER = "needs_browser"
    UNSUPPORTED_CONTENT = "unsupported_content"
    CONTENT_TOO_LARGE = "content_too_large"
    UNREADABLE_CONTENT = "unreadable_content"
    INVALID_PDF = "invalid_pdf"
    PDF_EXTRACTION_UNAVAILABLE = "pdf_extraction_unavailable"
    UNKNOWN_BACKEND = "unknown_backend"
    HOSTED_BACKEND_NOT_CONFIRMED = "hosted_backend_not_confirmed"
    BUDGET_EXCEEDED = "budget_exceeded"
    REPORT_REFUSED = "report_refused"
    BANK_NOT_FOUND = "bank_not_found"
    BANK_INVALID = "bank_invalid"
    BLACKLISTED = "blacklisted"
    TOMBSTONED = "tombstoned"
    ALREADY_WATCHED = "already_watched"
    ALREADY_BLACKLISTED = "already_blacklisted"


MESSAGES = {
    ErrorCode.HOST_NOT_ALLOWED: "Host header is not allowed.",
    ErrorCode.CSRF_TOKEN_INVALID: "Missing or invalid CSRF token.",
    ErrorCode.NOT_FOUND: "Not found.",
    ErrorCode.METHOD_NOT_ALLOWED: "Method not allowed.",
    ErrorCode.INVALID_REQUEST: "The request is invalid.",
    ErrorCode.HTTP_ERROR: "The request could not be handled.",
    ErrorCode.INTERNAL_ERROR: "The server hit an unexpected error.",
    ErrorCode.PAYLOAD_TOO_LARGE: "The request body is too large.",
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: "The content type is not supported here.",
    ErrorCode.EMPTY_POSTING: "The posting has no text. Paste the posting text.",
    ErrorCode.POSTING_TOO_LONG: "The posting text is too long.",
    ErrorCode.BLOCKED_BY_POLICY: "The link is blocked by the fetch policy.",
    ErrorCode.FETCH_FAILED: "The link could not be fetched. Paste the posting text instead.",
    ErrorCode.NEEDS_BROWSER: "The page needs a sign in. Paste the posting text instead.",
    ErrorCode.UNSUPPORTED_CONTENT: "The link did not return a supported kind of page.",
    ErrorCode.CONTENT_TOO_LARGE: "The page is too large.",
    ErrorCode.UNREADABLE_CONTENT: "The page could not be read as text. Paste the posting text.",
    ErrorCode.INVALID_PDF: "The upload is not a PDF.",
    ErrorCode.PDF_EXTRACTION_UNAVAILABLE: "PDF text extraction is not built yet. Paste the text.",
    ErrorCode.UNKNOWN_BACKEND: "That backend is not the configured one.",
    ErrorCode.HOSTED_BACKEND_NOT_CONFIRMED: "A hosted backend must be confirmed in the request.",
    ErrorCode.BUDGET_EXCEEDED: "The call would pass the configured budget.",
    ErrorCode.REPORT_REFUSED: "The report was refused because a claim could not be grounded.",
    ErrorCode.BANK_NOT_FOUND: "The fact bank file was not found.",
    ErrorCode.BANK_INVALID: "The fact bank is not valid.",
    ErrorCode.BLACKLISTED: "That company, board or domain is on the blacklist.",
    ErrorCode.TOMBSTONED: "A person denied that company or board, so it stays off the watchlist.",
    ErrorCode.ALREADY_WATCHED: "That company or board is already on the watchlist.",
    ErrorCode.ALREADY_BLACKLISTED: "That entry is already on the blacklist.",
}


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    problem: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ErrorBody


class ApiError(Exception):
    """A failure with a stable code. Later routes raise this and the handler shapes the answer."""

    def __init__(
        self, status_code: int, code: ErrorCode, details: list[ErrorDetail] | None = None
    ) -> None:
        super().__init__(code.value)
        self.status_code = status_code
        self.code = code
        self.details = details


HARDENING_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
)

FIELD_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
MAX_FIELD_CHARS = 80
UNKNOWN_PART = "?"


def safe_field(location: Sequence[object], *, last_is_unknown: bool) -> str:
    """A field path that never repeats a key the caller chose.

    Names that are not plain identifiers become `?`. When the error is an unexpected key, the
    last part is the caller's own key, so it becomes `?` as well. The result is capped."""
    parts = []
    for index, part in enumerate(location):
        is_unknown_key = last_is_unknown and index == len(location) - 1
        text = str(part)
        parts.append(text if not is_unknown_key and FIELD_PART.match(text) else UNKNOWN_PART)
    return ".".join(parts)[:MAX_FIELD_CHARS]


def details_from_errors(errors: Sequence[Mapping[str, Any]]) -> list[ErrorDetail]:
    return [
        ErrorDetail(
            field=safe_field(item["loc"], last_is_unknown=item["type"] == "extra_forbidden"),
            problem=str(item["msg"]),
        )
        for item in errors
    ]


def details_from_validation_error(error: ValidationError) -> list[ErrorDetail]:
    """Safe field paths and rule text only. The submitted values and keys are never copied."""
    return details_from_errors(
        error.errors(include_input=False, include_url=False, include_context=False)
    )


def error_response(
    status_code: int, code: ErrorCode, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=MESSAGES[code], details=details))
    return JSONResponse(body.model_dump(mode="json", exclude_none=True), status_code=status_code)


async def handle_api_error(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ApiError)
    return error_response(error.status_code, error.code, error.details)


async def handle_http_error(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)
    code = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.METHOD_NOT_ALLOWED}.get(
        error.status_code, ErrorCode.HTTP_ERROR
    )
    return error_response(error.status_code, code)


async def handle_validation_error(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    return error_response(422, ErrorCode.INVALID_REQUEST, details_from_errors(error.errors()))


async def handle_unexpected_error(request: Request, __: Exception) -> JSONResponse:
    """Starlette answers this one outside the app's own middleware, so it adds its own headers."""
    response = error_response(500, ErrorCode.INTERNAL_ERROR)
    for name, value in HARDENING_HEADERS:
        response.headers[name] = value
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(HTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
