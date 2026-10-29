# ABOUTME: Starts the real API server as a child process on its fixed port and talks to it.
# ABOUTME: Also checks that a non-loopback bind is refused before anything listens.
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
PORT = 5309
ENV = {
    "CYPRESS_CREEK_PROVIDER": "ollama",
    "CYPRESS_CREEK_MODEL": "qwen3.5:0.8b",
    "CYPRESS_CREEK_BASE_URL": "http://127.0.0.1:1",
}


def child_env(**extra: str) -> dict[str, str]:
    return {**os.environ, **ENV, **extra}


@contextmanager
def running_server() -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        [sys.executable, "-m", "cypress_creek.api.server"],
        cwd=ROOT,
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(
                    f"server exited early: {process.stderr.read() if process.stderr else ''}"
                )
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not start listening on port 5309")
        yield process
    finally:
        process.terminate()
        process.wait(timeout=10)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()


def fetch(path: str, host: str | None = None) -> tuple[int, dict[str, str], object]:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    try:
        connection.putrequest("GET", path, skip_host=host is not None)
        if host is not None:
            connection.putheader("Host", host)
        connection.endheaders()
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, json.loads(response.read())
    finally:
        connection.close()


def test_the_server_answers_on_loopback_and_enforces_the_host_check() -> None:
    with running_server():
        status, headers, body = fetch("/api/health")
        assert status == 200
        assert body == {
            "status": "ok",
            "backends": [
                {"provider": "ollama", "model": "qwen3.5:0.8b", "reachable": "unreachable"}
            ],
        }
        assert not [name for name in headers if name.startswith("access-control-")]

        status, _, body = fetch("/api/health", host="evil.example:5309")
        assert status == 403
        assert body == {
            "error": {"code": "host_not_allowed", "message": "Host header is not allowed."}
        }

        status, _, session = fetch("/api/session")
        assert status == 200
        assert isinstance(session, dict) and len(session["csrf_token"]) >= 32


def raw_request(
    method: str, path: str, headers: list[tuple[str, str]]
) -> tuple[int, dict[str, str], object]:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    try:
        connection.putrequest(method, path)
        for name, value in headers:
            connection.putheader(name, value)
        connection.putheader("Content-Length", "0")
        connection.endheaders()
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            json.loads(response.read()),
        )
    finally:
        connection.close()


def test_writes_need_exactly_one_right_token_on_the_real_server() -> None:
    with running_server():
        _, _, session = fetch("/api/session")
        assert isinstance(session, dict)
        token = session["csrf_token"]

        for method in ("POST", "PUT", "PATCH", "DELETE", "PURGE"):
            status, _, body = raw_request(method, "/api/anything", [])
            assert status == 403, method
            assert body == {
                "error": {"code": "csrf_token_invalid", "message": "Missing or invalid CSRF token."}
            }

        wrong = raw_request("POST", "/api/anything", [("X-CSRF-Token", "wrong" * 8)])
        twice = raw_request(
            "POST", "/api/anything", [("X-CSRF-Token", token), ("X-CSRF-Token", token)]
        )
        right = raw_request("POST", "/api/anything", [("X-CSRF-Token", token)])
        assert wrong[0] == 403
        assert twice[0] == 403
        assert right[0] == 404


def test_hardening_headers_come_with_every_real_answer() -> None:
    with running_server():
        ok = fetch("/api/health")
        refused = fetch("/api/health", host="evil.example:5309")
        missing = fetch("/api/nothing")

    for _, headers, _ in (ok, refused, missing):
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.2", "::1"])
def test_a_bind_other_than_127_0_0_1_is_refused_before_anything_listens(host: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "cypress_creek.api.server"],
        cwd=ROOT,
        env=child_env(CYPRESS_CREEK_API_HOST=host),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert "loopback" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_missing_provider_config_stops_the_server_with_a_clear_error() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CYPRESS_CREEK_")}
    env["CYPRESS_CREEK_CONFIG"] = str(ROOT / "no-such-config.toml")

    result = subprocess.run(
        [sys.executable, "-m", "cypress_creek.api.server"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert "config file not found" in result.stderr
