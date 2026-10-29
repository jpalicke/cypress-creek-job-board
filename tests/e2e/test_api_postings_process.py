# ABOUTME: Starts the real API server, pastes a posting, analyzes it with the backend down.
# ABOUTME: The report is read back. The database is a real file in a temporary data directory.
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


@contextmanager
def running_server(data_dir: Path) -> Iterator[None]:
    env = {
        **os.environ,
        "CYPRESS_CREEK_PROVIDER": "ollama",
        "CYPRESS_CREEK_MODEL": "qwen3.5:0.8b",
        "CYPRESS_CREEK_BASE_URL": "http://127.0.0.1:1",
        "CYPRESS_CREEK_DATA_DIR": str(data_dir),
        "CYPRESS_CREEK_BANK": str(ROOT / "evals" / "bank" / "sample_bank.yaml"),
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
    method: str, path: str, body: object = None, token: str | None = None
) -> tuple[int, object]:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-CSRF-Token"] = token
        payload = json.dumps(body) if body is not None else None
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_paste_analyze_and_read_the_stored_report_through_the_real_server(tmp_path: Path) -> None:
    with running_server(tmp_path):
        _, session = call("GET", "/api/session")
        assert isinstance(session, dict)
        token = session["csrf_token"]

        status, _ = call("POST", "/api/postings", {"source": "paste", "text": "Needs Python."})
        assert status == 403

        status, posting = call(
            "POST", "/api/postings", {"source": "paste", "text": "Needs Python."}, token
        )
        assert status == 201 and isinstance(posting, dict)

        status, analysis = call(
            "POST", f"/api/postings/{posting['id']}/analyze", {"backend": "ollama"}, token
        )
        assert status == 200 and isinstance(analysis, dict)
        assert analysis["report"]["status"] == "incomplete"

        status, stored = call("GET", f"/api/reports/{analysis['report_id']}")
        assert status == 200 and isinstance(stored, dict)
        assert stored["report"] == analysis["report"]

    assert (tmp_path / "cypress_creek.sqlite3").is_file()
