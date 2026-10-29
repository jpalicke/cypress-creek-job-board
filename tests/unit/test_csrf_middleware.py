# ABOUTME: Drives the CSRF middleware with hand built ASGI scopes, so odd methods can be sent.
# ABOUTME: Only the exact upper case safe methods skip the token, anything else needs it.
import asyncio
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from cypress_creek.api.security import CsrfMiddleware

TOKEN = "t" * 43


async def inner(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def status_for(method: str, headers: list[tuple[bytes, bytes]] | None = None) -> int:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": "/api/x",
        "headers": headers or [],
    }
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(CsrfMiddleware(inner, TOKEN)(scope, receive, send))
    return int(sent[0]["status"])


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_the_exact_safe_methods_need_no_token(method: str) -> None:
    assert status_for(method) == 200


@pytest.mark.parametrize("method", ["get", "Get", "head", "options", "gEt", "GET ", "", "POST"])
def test_any_other_spelling_or_method_needs_the_token(method: str) -> None:
    assert status_for(method) == 403
    assert status_for(method, [(b"x-csrf-token", TOKEN.encode())]) == 200
