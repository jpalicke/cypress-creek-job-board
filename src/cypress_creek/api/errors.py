# ABOUTME: The one typed error shape every API failure uses, with stable codes and fixed messages.
# ABOUTME: Messages never carry secrets, stack traces, submitted values or remote content.
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
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


MESSAGES = {
    ErrorCode.HOST_NOT_ALLOWED: "Host header is not allowed.",
    ErrorCode.CSRF_TOKEN_INVALID: "Missing or invalid CSRF token.",
    ErrorCode.NOT_FOUND: "Not found.",
    ErrorCode.METHOD_NOT_ALLOWED: "Method not allowed.",
    ErrorCode.INVALID_REQUEST: "The request is invalid.",
    ErrorCode.HTTP_ERROR: "The request could not be handled.",
    ErrorCode.INTERNAL_ERROR: "The server hit an unexpected error.",
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
    details = [
        ErrorDetail(field=".".join(str(part) for part in item["loc"]), problem=str(item["msg"]))
        for item in error.errors()
    ]
    return error_response(422, ErrorCode.INVALID_REQUEST, details)


async def handle_unexpected_error(_: Request, __: Exception) -> JSONResponse:
    return error_response(500, ErrorCode.INTERNAL_ERROR)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(HTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
