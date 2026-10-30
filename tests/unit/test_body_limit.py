# ABOUTME: Drives the body limit middleware with hand built ASGI scopes and request messages.
# ABOUTME: The limit counts the bytes it receives, so a missing or understated length is no way in.
import asyncio
import json

import pytest
from starlette.types import Message, Receive, Scope, Send

from cypress_creek.api.security import BodyLimitMiddleware

LIMIT = 1024
PDF_LIMIT = 10 * LIMIT
CHUNK = 256


class Probe:
    """An inner app that reads the whole body, and records what it got."""

    def __init__(self) -> None:
        self.called = False
        self.read = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True
        while True:
            message = await receive()
            self.read += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def scope_for(
    *,
    method: str = "POST",
    path: str = "/api/x",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Scope:
    return {"type": "http", "method": method, "path": path, "headers": headers or []}


def chunks(total: int) -> list[Message]:
    parts = [CHUNK] * (total // CHUNK) + ([total % CHUNK] if total % CHUNK else [])
    return [
        {"type": "http.request", "body": b"x" * size, "more_body": index < len(parts) - 1}
        for index, size in enumerate(parts)
    ] or [{"type": "http.request", "body": b"", "more_body": False}]


def run(
    scope: Scope, body_bytes: int, probe: Probe | None = None
) -> tuple[Probe, int, dict[str, object] | None]:
    inner = probe or Probe()
    messages = chunks(body_bytes)
    sent: list[Message] = []

    async def receive() -> Message:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = BodyLimitMiddleware(inner, default_limit=LIMIT, pdf_limit=PDF_LIMIT)
    asyncio.run(middleware(scope, receive, send))
    status = int(sent[0]["status"])
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return inner, status, json.loads(body) if status != 200 else None


def test_a_small_body_passes() -> None:
    inner, status, _ = run(scope_for(headers=[(b"content-length", b"100")]), 100)

    assert status == 200
    assert inner.read == 100


def test_a_declared_length_over_the_limit_is_refused_before_anything_is_read() -> None:
    inner, status, body = run(scope_for(headers=[(b"content-length", str(LIMIT + 1).encode())]), 5)

    assert status == 413
    assert body == {
        "error": {"code": "payload_too_large", "message": "The request body is too large."}
    }
    assert not inner.called


def test_a_body_with_no_length_is_counted_and_stopped_at_the_limit() -> None:
    inner, status, body = run(scope_for(), 100 * LIMIT)

    assert status == 413
    assert body is not None and body["error"]["code"] == "payload_too_large"  # type: ignore[index]
    assert inner.read <= LIMIT + CHUNK


def test_an_understated_length_cannot_hide_a_large_body() -> None:
    inner, status, _ = run(scope_for(headers=[(b"content-length", b"10")]), 100 * LIMIT)

    assert status == 413
    assert inner.read <= LIMIT + CHUNK


def test_a_chunked_body_within_the_limit_is_accepted() -> None:
    inner, status, _ = run(scope_for(headers=[(b"transfer-encoding", b"chunked")]), LIMIT)

    assert status == 200
    assert inner.read == LIMIT


def test_a_chunked_body_over_the_limit_is_refused() -> None:
    _, status, _ = run(scope_for(headers=[(b"transfer-encoding", b"chunked")]), LIMIT + 1)

    assert status == 413


def test_a_bad_content_length_is_ignored_in_favor_of_counting() -> None:
    _, small, _ = run(scope_for(headers=[(b"content-length", b"abc")]), 10)
    _, large, _ = run(scope_for(headers=[(b"content-length", b"abc")]), 100 * LIMIT)

    assert (small, large) == (200, 413)


PDF = [(b"content-type", b"application/pdf")]


def test_the_pdf_limit_applies_to_the_posting_upload_route_only() -> None:
    _, upload_ok, _ = run(scope_for(path="/api/postings", headers=PDF), 5 * LIMIT)
    _, upload_big, _ = run(scope_for(path="/api/postings", headers=PDF), 11 * LIMIT)
    _, other_route, _ = run(scope_for(path="/api/facts/validate", headers=PDF), 5 * LIMIT)
    _, wrong_method, _ = run(scope_for(method="PUT", path="/api/postings", headers=PDF), 5 * LIMIT)

    assert (upload_ok, upload_big, other_route, wrong_method) == (200, 413, 413, 413)


@pytest.mark.parametrize("media", [b"application/json", b"text/plain", b""])
def test_other_content_types_get_the_small_limit_on_the_upload_route(media: bytes) -> None:
    _, status, _ = run(
        scope_for(path="/api/postings", headers=[(b"content-type", media)]), 5 * LIMIT
    )

    assert status == 413


def test_non_http_scopes_pass_through() -> None:
    probe = Probe()
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(BodyLimitMiddleware(probe, LIMIT, PDF_LIMIT)({"type": "lifespan"}, receive, send))

    assert probe.called
