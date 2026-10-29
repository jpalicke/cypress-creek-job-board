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


def require_csrf(request: Request) -> None:
    """Every write needs the session token in a header, compared in constant time."""
    if request.method not in WRITE_METHODS:
        return
    sent = request.headers.get(TOKEN_HEADER, "")
    expected: str = request.app.state.csrf_token
    if not sent or not hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8")):
        raise ApiError(403, ErrorCode.CSRF_TOKEN_INVALID)
