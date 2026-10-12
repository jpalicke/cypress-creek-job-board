# ABOUTME: Runs the blacklist filter in real child Python processes over a real SQLite file.
# ABOUTME: Proves variants stay blocked across processes and that deciding never opens a socket.
import json
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cypress_creek.discovery.blacklist import BlacklistEntry, BlockReason
from cypress_creek.discovery.blacklist_repository import Blacklist
from cypress_creek.storage.db import connect, migrate

# The child installs a real recording guard on the socket entry points, loads the blacklist
# from the database file, decides each candidate and prints the results and the attempt count.
# A raw string keeps the \u escapes literal so the child source stays ASCII.
CHILD = r"""
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

from cypress_creek.discovery.blacklist import BlacklistEntry, BlockReason, Candidate
from cypress_creek.discovery.blacklist import is_blacklisted
from cypress_creek.discovery.blacklist_repository import Blacklist
from cypress_creek.storage.db import connect

attempts = []


def refuse(name):
    def guarded(*args, **kwargs):
        attempts.append(name)
        raise OSError("network call attempted: " + name)

    return guarded


socket.socket.connect = refuse("socket.connect")
socket.create_connection = refuse("create_connection")
socket.getaddrinfo = refuse("getaddrinfo")

database, mode = sys.argv[1], sys.argv[2]
conn = connect(Path(database))
blacklist = Blacklist(conn)
if mode == "add":
    now = datetime.now(UTC)
    blacklist.add(BlacklistEntry(BlockReason.COMPANY_KEY, "Wayne Enterprises", "by a child", now))
if mode == "probe":
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError:
        pass
entries = blacklist.entries()
candidates = [
    Candidate("Acme Corp", None, None),
    Candidate("Аcme Corp", None, None),
    Candidate("Ac‍me Corp", None, None),
    Candidate("ACME, Inc.", None, None),
    Candidate("Other", " GLOBEX ", None),
    Candidate("Other", None, "https://WWW.Initech.com:8443/jobs"),
    Candidate("Wayne Enterprises LLC", None, None),
    Candidate("Hooli", "hooli", "hooli.com"),
]
results = [is_blacklisted(c, entries) for c in candidates]
print(json.dumps({"results": results, "attempts": attempts}))
conn.close()
"""


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "app.sqlite3"
    conn = connect(path)
    migrate(conn)
    added_at = datetime(2026, 1, 1, tzinfo=UTC)
    blacklist = Blacklist(conn)
    for kind, value in [
        (BlockReason.COMPANY_KEY, "Acme Corp"),
        (BlockReason.SLUG, "globex"),
        (BlockReason.DOMAIN, "initech.com"),
    ]:
        blacklist.add(BlacklistEntry(kind, value, "not a fit", added_at))
    conn.close()
    yield path


def _run_child(database: Path, mode: str) -> dict[str, list[str | None]]:
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(database), mode],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    parsed: dict[str, list[str | None]] = json.loads(result.stdout)
    return parsed


BASE_RESULTS = [
    "company_key",
    "company_key",
    "company_key",
    "company_key",
    "slug",
    "domain",
    None,
    None,
]


def test_variants_are_blocked_in_a_child_process_with_no_socket_attempt(database: Path) -> None:
    outcome = _run_child(database, "read")
    assert outcome["results"] == BASE_RESULTS
    assert outcome["attempts"] == []


def test_a_second_process_reopening_the_database_still_blocks(database: Path) -> None:
    first = _run_child(database, "add")
    assert first["results"] == [*BASE_RESULTS[:6], "company_key", None]
    assert first["attempts"] == []

    second = _run_child(database, "read")
    assert second["results"] == [*BASE_RESULTS[:6], "company_key", None]
    assert second["attempts"] == []

    reopened = sqlite3.connect(database)
    try:
        (count,) = reopened.execute("SELECT COUNT(*) FROM blacklist_entry").fetchone()
    finally:
        reopened.close()
    assert count == 4


def test_the_child_guard_records_a_deliberate_lookup(database: Path) -> None:
    outcome = _run_child(database, "probe")
    assert outcome["attempts"] == ["getaddrinfo"]
