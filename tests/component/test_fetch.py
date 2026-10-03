# ABOUTME: Tests posting fetch results and typed failures against real local HTTP responses.
# ABOUTME: The private test seam uses the same transport with a fixture-only resolver.
import sys
from datetime import UTC, datetime
from inspect import signature
from pathlib import Path

import pytest
from http_support import http_server, local_target

from cypress_creek import __version__
from cypress_creek.ingest.fetch import (
    BlockedByPolicy,
    Empty,
    FetchFailed,
    NeedsBrowser,
    TooLarge,
    UnsupportedContent,
    _fetch_posting,
    fetch_posting,
)
from cypress_creek.ingest.safe_http import FetchLimits, FetchResponse, _fetch, _run_worker

WORKER = [sys.executable, str(Path(__file__).parents[1] / "http_support.py"), "--worker"]


def _live_fetch(url: str, limits: FetchLimits) -> FetchResponse:
    return _fetch(url, limits, resolve=local_target)


@pytest.mark.parametrize(
    ("path", "body", "content_type"),
    [
        ("/ok", b"public posting", "text/plain"),
        ("/html", b"<main>Public posting</main>", "text/html"),
        ("/pdf", b"%PDF-1.4\npublic posting\n", "application/pdf"),
    ],
)
def test_raw_posting_and_provenance(path: str, body: bytes, content_type: str) -> None:
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}{path}"
        before = datetime.now(UTC)
        result = _fetch_posting(url, FetchLimits(), transport=_live_fetch)
        after = datetime.now(UTC)
    assert len(requests.received) == 1
    assert result.body == body
    assert result.content_type == content_type
    assert result.provenance.requested_url == url
    assert result.provenance.final_url == url
    assert result.provenance.byte_count == len(body)
    assert before <= result.provenance.retrieved_at <= after
    assert result.provenance.extractor_name == "raw-fetch"
    assert result.provenance.extractor_version == __version__
    assert result.provenance.warnings == ()


def test_cross_host_redirect_is_recorded() -> None:
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/cross-host"
        result = _fetch_posting(url, FetchLimits(), transport=_live_fetch)
    assert len(requests.received) == 2
    assert result.provenance.requested_url == url
    assert result.provenance.final_url == f"http://other-fixture.test:{port}/ok"
    assert result.provenance.warnings == ("cross_host_redirect",)


@pytest.mark.parametrize(
    ("path", "failure"),
    [
        ("/wrong-type", UnsupportedContent),
        ("/json", UnsupportedContent),
        ("/empty", Empty),
        ("/login", NeedsBrowser),
        ("/forbidden", FetchFailed),
        ("/error", FetchFailed),
        ("/private", BlockedByPolicy),
    ],
)
def test_real_response_has_typed_failure(path: str, failure: type[Exception]) -> None:
    with http_server() as (port, requests), pytest.raises(failure) as caught:
        _fetch_posting(f"http://fixture.test:{port}{path}", FetchLimits(), transport=_live_fetch)
    assert len(requests.received) == 1
    assert "fixture.test" not in str(caught.value)
    assert "private" not in str(caught.value)
    if path == "/private":
        assert isinstance(caught.value, BlockedByPolicy)
        assert caught.value.reason_code == "unsafe_address"


def test_server_byte_cap_is_too_large() -> None:
    with http_server() as (port, _), pytest.raises(TooLarge):
        _fetch_posting(
            f"http://fixture.test:{port}/large",
            FetchLimits(max_wire_bytes=64),
            transport=_live_fetch,
        )


def test_decompression_ratio_is_too_large() -> None:
    with http_server() as (port, _), pytest.raises(TooLarge):
        _fetch_posting(f"http://fixture.test:{port}/bomb", FetchLimits(), transport=_live_fetch)


def test_public_entry_preserves_policy() -> None:
    with pytest.raises(BlockedByPolicy) as caught:
        fetch_posting("http://127.0.0.1/private")
    assert caught.value.reason_code == "unsafe_address"


def test_public_entry_has_fixed_fetch_policy() -> None:
    assert list(signature(fetch_posting).parameters) == ["url"]


def test_login_signal_survives_worker_protocol() -> None:
    with http_server() as (port, _), pytest.raises(NeedsBrowser) as caught:
        _fetch_posting(
            f"http://fixture.test:{port}/login",
            FetchLimits(),
            transport=lambda url, limits: _run_worker(url, limits, WORKER),
        )
    assert "paste" in str(caught.value).lower()


def test_empty_response_guides_manual_paste() -> None:
    with http_server() as (port, _), pytest.raises(Empty) as caught:
        _fetch_posting(f"http://fixture.test:{port}/empty", FetchLimits(), transport=_live_fetch)
    assert "paste" in str(caught.value).lower()
