# ABOUTME: Starts the real API server and drives the discovery routes against a blacklisted board.
# ABOUTME: A blocked board is never fetched, so nothing leaves the machine and the run is offline.
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cypress_creek.discovery.blacklist import BlacklistEntry, BlockReason
from cypress_creek.discovery.blacklist_repository import Blacklist
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.storage.db import connect
from cypress_creek.storage.repository import prepare_database

ROOT = Path(__file__).parent.parent.parent
PORT = 5309
APPROVED = datetime(2026, 1, 1, tzinfo=UTC)


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


def seed(data_dir: Path) -> None:
    """A watchlist whose only company is blacklisted, so a run must not fetch anything."""
    path = data_dir / "cypress_creek.sqlite3"
    prepare_database(path)
    conn = connect(path)
    try:
        Watchlist(conn).add(
            WatchlistEntry("Blocked Co", "greenhouse", "blockedco", IdentityEvidence.WEAK, APPROVED)
        )
        Blacklist(conn).add(
            BlacklistEntry(BlockReason.COMPANY_KEY, "Blocked Co", "not a fit", APPROVED)
        )
    finally:
        conn.close()


def test_refresh_and_list_on_the_real_server_skip_a_blacklisted_board(tmp_path: Path) -> None:
    seed(tmp_path)
    with running_server(tmp_path):
        _, session = call("GET", "/api/session")
        assert isinstance(session, dict)
        token = session["csrf_token"]

        status, _ = call("POST", "/api/discovery/refresh", {"backend": "ollama"})
        assert status == 403

        status, summary = call("POST", "/api/discovery/refresh", {"backend": "ollama"}, token)
        assert status == 200 and isinstance(summary, dict)
        assert summary["blocked_boards"] == 1
        assert summary["fetched"] == 0
        assert summary["errors"] == []
        assert summary["stopped_by"] is None

        status, listed = call("GET", "/api/discovery/listings")
        assert status == 200 and isinstance(listed, dict)
        assert listed["listings"] == []
        assert "triage" in listed["note"]


def test_a_refresh_with_a_backend_that_is_not_configured_is_a_typed_error(tmp_path: Path) -> None:
    seed(tmp_path)
    with running_server(tmp_path):
        _, session = call("GET", "/api/session")
        assert isinstance(session, dict)

        status, error = call(
            "POST", "/api/discovery/refresh", {"backend": "openai"}, session["csrf_token"]
        )

    assert status == 422 and isinstance(error, dict)
    assert error["error"]["code"] == "unknown_backend"
