# ABOUTME: Starts the real API server and drives the watchlist and blacklist routes over HTTP.
# ABOUTME: The lists live in a real database file that a second server start reads back.
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

from cypress_creek.storage.company_key import company_key

ROOT = Path(__file__).parent.parent.parent
PORT = 5309
ADD = {
    "display_name": "Acme Corp",
    "ats": "greenhouse",
    "slug": "acme",
    "identity_evidence": "strong",
    "approval": "human_confirmed",
}


@contextmanager
def running_server(data_dir: Path) -> Iterator[None]:
    env = {
        **os.environ,
        "CYPRESS_CREEK_PROVIDER": "ollama",
        "CYPRESS_CREEK_MODEL": "qwen3.5:0.8b",
        "CYPRESS_CREEK_BASE_URL": "http://127.0.0.1:1",
        "CYPRESS_CREEK_DATA_DIR": str(data_dir),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "cypress_creek.api.server"],
        cwd=ROOT,
        env=env,
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
        yield
    finally:
        process.terminate()
        process.wait(timeout=10)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()


def call(
    method: str, path: str, body: object | None = None, token: str | None = None
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    try:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-CSRF-Token"] = token
        payload = json.dumps(body) if body is not None else None
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        parsed: dict[str, object] = json.loads(response.read())
        return response.status, parsed
    finally:
        connection.close()


def session_token() -> str:
    _, body = call("GET", "/api/session")
    return str(body["csrf_token"])


def test_a_blacklist_blocks_the_watchlist_and_both_lists_survive_a_restart(
    tmp_path: Path,
) -> None:
    with running_server(tmp_path):
        token = session_token()
        assert call("POST", "/api/watchlist", ADD)[0] == 403
        status, entry = call(
            "POST",
            "/api/blacklist",
            {"match_kind": "company_key", "value": "Initech", "reason": "agency"},
            token,
        )
        assert status == 201
        status, refused = call(
            "POST", "/api/watchlist", {**ADD, "display_name": "INITECH, Inc.", "slug": "i"}, token
        )
        assert status == 409
        assert refused["error"]["code"] == "blacklisted"  # type: ignore[index]
        assert call("POST", "/api/watchlist", ADD, token)[0] == 201
    with running_server(tmp_path):
        token = session_token()
        _, watch = call("GET", "/api/watchlist")
        _, block = call("GET", "/api/blacklist")
        assert [e["slug"] for e in watch["entries"]] == ["acme"]  # type: ignore[attr-defined]
        assert [e["value"] for e in block["entries"]] == [company_key("Initech")]  # type: ignore[attr-defined]
        assert call("DELETE", f"/api/blacklist/{entry['id']}", None, token)[0] == 200
        assert call("GET", "/api/blacklist")[1] == {"entries": []}
