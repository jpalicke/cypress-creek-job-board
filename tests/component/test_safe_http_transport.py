# ABOUTME: Exercises transport limits, redirects and deadlines against real loopback HTTP servers.
# ABOUTME: Production refuses local destinations even when test-looking environment is set.
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from http_support import http_server, local_target

from cypress_creek.ingest.safe_http import (
    FetchLimits,
    SafeHttpError,
    _fetch,
    _run_worker,
    fetch_url,
)
from cypress_creek.ingest.url_guard import UrlGuardError

WORKER = [sys.executable, str(Path(__file__).parents[1] / "http_support.py"), "--worker"]


def test_streamed_content_and_request_identity() -> None:
    with http_server() as (port, requests):
        url = f"http://fixture.test:{port}/a%2Fb?q=x%20y%0D%0A#ignored"
        response = _fetch(url, FetchLimits(), resolve=local_target)
    assert response.body == b"public posting"
    assert response.status == 200
    assert response.content_type == "text/plain"
    path, headers = requests.received[0]
    assert path == "/a%2Fb?q=x%20y%0D%0A"
    assert headers["host"] == f"fixture.test:{port}"
    assert headers["accept-encoding"] == "gzip"
    assert "cookie" not in headers
    assert "authorization" not in headers


def test_three_redirects_work_without_replaying_cookies() -> None:
    with http_server() as (port, requests):
        response = _fetch(
            f"http://fixture.test:{port}/redirect/3", FetchLimits(), resolve=local_target
        )
    assert response.body == b"public posting"
    assert response.url == f"http://fixture.test:{port}/ok"
    assert len(requests.received) == 4
    assert all("cookie" not in headers for _, headers in requests.received)


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/redirect/4", "too_many_redirects"),
        ("/bad-location", "invalid_redirect"),
        ("/no-location", "invalid_redirect"),
        ("/wrong-type", "unsupported_content"),
        ("/missing-type", "unsupported_content"),
        ("/error", "http_status"),
        ("/encoding", "invalid_encoding"),
        ("/bad-gzip", "invalid_encoding"),
        ("/short-gzip", "invalid_encoding"),
        ("/two-gzip", "invalid_encoding"),
        ("/bomb", "decompression_ratio"),
    ],
)
def test_real_responses_fail_closed(path: str, reason: str) -> None:
    with http_server() as (port, _), pytest.raises(SafeHttpError) as caught:
        _fetch(f"http://fixture.test:{port}{path}", FetchLimits(), resolve=local_target)
    assert caught.value.reason_code == reason
    assert "private server" not in str(caught.value)
    assert "fixture.test" not in str(caught.value)


def test_private_redirect_is_validated_before_connection() -> None:
    with http_server() as (port, requests), pytest.raises(UrlGuardError) as caught:
        _fetch(f"http://fixture.test:{port}/private", FetchLimits(), resolve=local_target)
    assert caught.value.reason_code == "unsafe_address"
    assert len(requests.received) == 1


@pytest.mark.parametrize("path", ["/ok", "/gzip", "/large"])
def test_decoded_size_cap_is_enforced_during_streaming(path: str) -> None:
    with http_server() as (port, _), pytest.raises(SafeHttpError) as caught:
        _fetch(
            f"http://fixture.test:{port}{path}",
            FetchLimits(max_decoded_bytes=12),
            resolve=local_target,
        )
    assert caught.value.reason_code == "too_large"


def test_wire_size_cap_applies_without_content_length() -> None:
    with http_server() as (port, _), pytest.raises(SafeHttpError) as caught:
        _fetch(
            f"http://fixture.test:{port}/large",
            FetchLimits(max_wire_bytes=64),
            resolve=local_target,
        )
    assert caught.value.reason_code == "too_large"


def test_gzip_is_decoded() -> None:
    with http_server() as (port, _):
        response = _fetch(f"http://fixture.test:{port}/gzip", FetchLimits(), resolve=local_target)
    assert response.body == b"public posting"


@pytest.mark.parametrize("path", ["/slow-body", "/slow-headers", "/slow-headers-trickle"])
def test_whole_request_deadline_stops_trickling(path: str) -> None:
    with http_server() as (port, requests):
        started = time.monotonic()
        with pytest.raises(SafeHttpError) as caught:
            _run_worker(f"http://fixture.test:{port}{path}", FetchLimits(total_timeout=2), WORKER)
        elapsed = time.monotonic() - started
    assert caught.value.reason_code == "timeout"
    assert elapsed < 4
    assert requests.received, "The deadline test must reach the real server."


def test_production_entry_cannot_enable_the_test_resolver() -> None:
    environment = dict(os.environ)
    environment.update(TESTING="true", CYPRESS_CREEK_ALLOW_LOCALHOST="true")
    consumer = """
from cypress_creek.ingest.safe_http import fetch_url
from cypress_creek.ingest.url_guard import UrlGuardError
try:
    fetch_url('http://127.0.0.1/')
except UrlGuardError as error:
    print(error.reason_code)
else:
    raise SystemExit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", consumer],
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.strip() == "unsafe_address"


def test_public_entry_refuses_credentials_without_echoing_them() -> None:
    with pytest.raises(UrlGuardError) as caught:
        fetch_url("http://private-user@1.1.1.1/")
    assert caught.value.reason_code == "credentials"
    assert "private-user" not in str(caught.value)


def test_worker_transfers_successful_bytes() -> None:
    with http_server() as (port, _):
        response = _run_worker(f"http://fixture.test:{port}/gzip", FetchLimits(), WORKER)
    assert response.body == b"public posting"


def test_worker_transfers_redacted_transport_error() -> None:
    with http_server() as (port, _), pytest.raises(SafeHttpError) as caught:
        _run_worker(f"http://fixture.test:{port}/error", FetchLimits(), WORKER)
    assert caught.value.reason_code == "http_status"
    assert "private server" not in str(caught.value)


def test_worker_start_failure_is_redacted(tmp_path: Path) -> None:
    with pytest.raises(SafeHttpError) as caught:
        _run_worker("https://1.1.1.1/", FetchLimits(), [str(tmp_path / "absent-executable")])
    assert caught.value.reason_code == "network_error"
    assert str(tmp_path) not in str(caught.value)


def test_socket_read_timeout_is_redacted() -> None:
    with http_server() as (port, _), pytest.raises(SafeHttpError) as caught:
        _fetch(
            f"http://fixture.test:{port}/slow-headers",
            FetchLimits(total_timeout=0.1),
            resolve=local_target,
        )
    assert caught.value.reason_code == "timeout"


def test_refused_connection_is_redacted() -> None:
    with http_server() as (port, _):
        url = f"http://fixture.test:{port}/ok"
    with pytest.raises(SafeHttpError) as caught:
        _fetch(url, FetchLimits(), resolve=local_target)
    assert caught.value.reason_code == "network_error"
    assert "fixture.test" not in str(caught.value)
