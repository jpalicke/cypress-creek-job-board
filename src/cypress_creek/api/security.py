# ABOUTME: The Host header check and the per-session CSRF token that every request inherits.
# ABOUTME: Together they block DNS rebinding and cross-site writes against a localhost service.
import hmac
import secrets

from starlette.datastructures import MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cypress_creek.api.errors import HARDENING_HEADERS, ErrorCode, error_response

API_PORT = 5309
TOKEN_HEADER = "X-CSRF-Token"
MAX_BODY_BYTES = 1024 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024
PDF_UPLOAD_ROUTE = ("POST", "/api/postings")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOKEN_HEADER_BYTES = TOKEN_HEADER.lower().encode("ascii")
TOKEN_BYTES = 32


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


class _BodyTooLarge(Exception):
    """Raised inside the receive channel when the bytes read pass the limit."""


class BodyLimitMiddleware:
    """Stops a request body at a byte limit, whatever its headers claim.

    A declared length over the limit is refused before anything is read. Every body is also
    counted as it is received, so a missing, wrong or chunked length cannot let more through. The
    larger PDF limit applies only to the posting upload route (`POST /api/postings`)."""

    def __init__(self, app: ASGIApp, default_limit: int, pdf_limit: int) -> None:
        self._app = app
        self._default_limit = default_limit
        self._pdf_limit = pdf_limit

    def _limit_for(self, scope: Scope, headers: dict[bytes, bytes]) -> int:
        media = headers.get(b"content-type", b"").split(b";")[0].strip().lower()
        is_upload = (scope["method"], scope["path"]) == PDF_UPLOAD_ROUTE
        return self._pdf_limit if is_upload and media == b"application/pdf" else self._default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {name: value for name, value in scope["headers"]}
        limit = self._limit_for(scope, headers)
        try:
            declared = int(headers.get(b"content-length", b"0") or b"0")
        except ValueError:
            declared = 0
        refusal: Response = error_response(413, ErrorCode.PAYLOAD_TOO_LARGE)
        if declared > limit:
            await refusal(scope, receive, send)
            return
        received = 0
        started = False

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise _BodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self._app(scope, counted_receive, tracked_send)
        except _BodyTooLarge:
            if started:
                raise
            await refusal(scope, receive, send)


class CsrfMiddleware:
    """Every request that is not known to be safe needs the session token, exactly once.

    This is middleware and not a route dependency, so it covers mounted sub-apps, unknown paths
    and methods nobody registered. Only the exact upper case GET, HEAD and OPTIONS skip it.
    The comparison is in constant time. It runs after the Host check."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = token.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self._app(scope, receive, send)
            return
        sent = [value for name, value in scope["headers"] if name == TOKEN_HEADER_BYTES]
        if len(sent) == 1 and hmac.compare_digest(sent[0], self._expected):
            await self._app(scope, receive, send)
            return
        response: Response = error_response(403, ErrorCode.CSRF_TOKEN_INVALID)
        await response(scope, receive, send)


class SecurityHeadersMiddleware:
    """Adds hardening headers to every answer, including the ones other middleware sends.

    `Cache-Control: no-store` goes on the API only, so the static bundle can be cached."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        is_api = scope["path"].startswith("/api/") or scope["path"] == "/api"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HARDENING_HEADERS:
                    headers[name] = value
                if is_api:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self._app(scope, receive, send_with_headers)
