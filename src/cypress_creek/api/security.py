# ABOUTME: The Host header check and the per-session CSRF token that every request inherits.
# ABOUTME: Together they block DNS rebinding and cross-site writes against a localhost service.
import hmac
import secrets

from fastapi import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from cypress_creek.api.errors import ApiError, ErrorCode, error_response

API_PORT = 5309
TOKEN_HEADER = "X-CSRF-Token"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TOKEN_BYTES = 32
MAX_BODY_BYTES = 1024 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024


def allowed_hosts(port: int) -> frozenset[str]:
    """The only Host header values the API accepts: the two loopback names with the port."""
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


class HostCheckMiddleware:
    """Rejects any request whose single Host header is not an allowed loopback name and port."""

    def __init__(self, app: ASGIApp, allowed: frozenset[str]) -> None:
        self._app = app
        self._allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return
        hosts = [value for name, value in scope["headers"] if name == b"host"]
        if len(hosts) == 1 and self._is_allowed(hosts[0]):
            await self._app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response: Response = error_response(403, ErrorCode.HOST_NOT_ALLOWED)
        await response(scope, receive, send)

    def _is_allowed(self, raw: bytes) -> bool:
        try:
            return raw.decode("ascii").casefold() in self._allowed
        except UnicodeDecodeError:
            return False


class BodyLimitMiddleware:
    """Refuses a body whose declared length is over the limit, and any body without a length.

    The server reads exactly the declared number of bytes, so the declared length is the limit.
    A PDF upload may be larger than a JSON body."""

    def __init__(self, app: ASGIApp, default_limit: int, pdf_limit: int) -> None:
        self._app = app
        self._default_limit = default_limit
        self._pdf_limit = pdf_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {name: value for name, value in scope["headers"]}
        refusal = self._refusal(headers)
        if refusal is None:
            await self._app(scope, receive, send)
            return
        response: Response = refusal
        await response(scope, receive, send)

    def _refusal(self, headers: dict[bytes, bytes]) -> Response | None:
        if b"transfer-encoding" in headers:
            return error_response(411, ErrorCode.LENGTH_REQUIRED)
        try:
            length = int(headers.get(b"content-length", b"0") or b"0")
        except ValueError:
            return error_response(411, ErrorCode.LENGTH_REQUIRED)
        media = headers.get(b"content-type", b"").split(b";")[0].strip().lower()
        limit = self._pdf_limit if media == b"application/pdf" else self._default_limit
        if length < 0:
            return error_response(411, ErrorCode.LENGTH_REQUIRED)
        if length > limit:
            return error_response(413, ErrorCode.PAYLOAD_TOO_LARGE)
        return None


def require_csrf(request: Request) -> None:
    """Every write needs the session token in a header, compared in constant time."""
    if request.method not in WRITE_METHODS:
        return
    sent = request.headers.get(TOKEN_HEADER, "")
    expected: str = request.app.state.csrf_token
    if not sent or not hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8")):
        raise ApiError(403, ErrorCode.CSRF_TOKEN_INVALID)
