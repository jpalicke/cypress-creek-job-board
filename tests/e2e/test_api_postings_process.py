# ABOUTME: Starts the real API server, pastes a posting, analyzes it with the backend down.
# ABOUTME: The report is read back. The database is a real file in a temporary data directory.
import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from api_server_support import PORT, ROOT, call, running_server


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


def test_the_database_is_created_and_migrated_when_the_server_starts(tmp_path: Path) -> None:
    with running_server(tmp_path):
        database = tmp_path / "cypress_creek.sqlite3"
        assert database.is_file()
        with closing(sqlite3.connect(database)) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
    assert {"posting", "report", "schema_version"} <= tables


def test_a_database_that_cannot_be_prepared_stops_the_server_with_a_clear_error(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file where the data directory should be", encoding="utf-8")
    env = {
        **os.environ,
        "CYPRESS_CREEK_PROVIDER": "ollama",
        "CYPRESS_CREEK_MODEL": "qwen3.5:0.8b",
        "CYPRESS_CREEK_DATA_DIR": str(blocker / "data"),
    }

    try:
        result = subprocess.run(
            [sys.executable, "-m", "cypress_creek.api.server"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the server kept running although its database could not be prepared")

    assert result.returncode == 2
    assert "the database could not be prepared" in result.stderr
    assert "Traceback" not in result.stderr


def raw_post(token: str, head_lines: list[str], body_parts: list[bytes]) -> bytes:
    """A POST to /api/postings written onto a real socket, then the start of the answer."""
    request = (
        "POST /api/postings HTTP/1.1\r\nHost: 127.0.0.1:5309\r\nConnection: close\r\n"
        f"Content-Type: application/json\r\nX-CSRF-Token: {token}\r\n"
        + "".join(line + "\r\n" for line in head_lines)
        + "\r\n"
    ).encode()
    with socket.create_connection(("127.0.0.1", PORT), timeout=10) as connection:
        connection.sendall(request)
        try:
            for part in body_parts:
                connection.sendall(part)
        except OSError:
            pass  # the server may close the connection early, which is the point
        connection.settimeout(10)
        answer = b""
        try:
            while chunk := connection.recv(65536):
                answer += chunk
        except OSError:
            pass
    return answer


def test_a_large_chunked_or_understated_body_is_stopped_on_the_real_server(tmp_path: Path) -> None:
    big = b" " * (64 * 1024)
    with running_server(tmp_path):
        _, session = call("GET", "/api/session")
        assert isinstance(session, dict)
        token = session["csrf_token"]

        chunked = raw_post(
            token,
            ["Transfer-Encoding: chunked"],
            [f"{len(big):x}\r\n".encode() + big + b"\r\n" for _ in range(40)] + [b"0\r\n\r\n"],
        )
        understated = raw_post(token, ["Content-Length: 10"], [big] * 40)
        declared = raw_post(token, [f"Content-Length: {5 * 1024 * 1024}"], [])
        after, _ = call("GET", "/api/health")

    assert chunked.startswith(b"HTTP/1.1 413")
    assert b"payload_too_large" in chunked
    assert understated.startswith((b"HTTP/1.1 413", b"HTTP/1.1 400"))
    assert declared.startswith(b"HTTP/1.1 413")
    assert after == 200
