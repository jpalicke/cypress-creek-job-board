# ABOUTME: Tests the blacklist table and repository on real temp SQLite files, and the socket guard.
# ABOUTME: Proves the filter blocks DB-loaded entries and never touches the network while doing so.
import socket
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest

from cypress_creek.discovery.blacklist import (
    BlacklistEntry,
    BlockReason,
    Candidate,
    is_blacklisted,
)
from cypress_creek.discovery.blacklist_repository import AlreadyBlacklisted, Blacklist
from cypress_creek.storage.db import connect, migrate, schema_version

ADDED_AT = datetime(2026, 1, 1, tzinfo=UTC)
# Latin "Acme Corp" with a Cyrillic A (U+0410), and with a zero width joiner (U+200D) inside.
CYRILLIC_A_ACME = "Аcme Corp"
ZERO_WIDTH_ACME = "Ac‍me Corp"


def _entry(kind: BlockReason = BlockReason.COMPANY_KEY, value: str = "Acme Corp") -> BlacklistEntry:
    return BlacklistEntry(match_kind=kind, value=value, reason="not a fit", added_at=ADDED_AT)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "app.sqlite3"
    conn = connect(path)
    migrate(conn)
    conn.close()
    return path


@pytest.fixture
def conn(database: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(database)
    yield connection
    connection.close()


def test_the_migration_creates_the_blacklist_table(conn: sqlite3.Connection) -> None:
    tables = {
        name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "blacklist_entry" in tables
    assert schema_version(conn) >= 3


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO blacklist_entry (match_kind, value, reason, added_at)"
        " VALUES ('nonsense', 'acme', 'r', 't')",
        "INSERT INTO blacklist_entry (match_kind, value, reason, added_at)"
        " VALUES ('slug', '', 'r', 't')",
        "INSERT INTO blacklist_entry (match_kind, value, reason, added_at)"
        " VALUES ('slug', NULL, 'r', 't')",
    ],
)
def test_the_database_refuses_a_bad_match_kind_or_an_empty_value(
    conn: sqlite3.Connection, statement: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(statement)


def test_the_database_refuses_a_duplicate_kind_and_value(conn: sqlite3.Connection) -> None:
    statement = (
        "INSERT INTO blacklist_entry (match_kind, value, reason, added_at)"
        " VALUES ('slug', 'acme', 'r', 't')"
    )
    conn.execute(statement)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(statement)


def test_entries_round_trip_and_survive_reopening(database: Path) -> None:
    first = connect(database)
    blacklist = Blacklist(first)
    entries = [
        _entry(BlockReason.COMPANY_KEY, "Acme Corp"),
        _entry(BlockReason.SLUG, "Globex"),
        _entry(BlockReason.DOMAIN, "https://www.Initech.com/jobs"),
    ]
    ids = [blacklist.add(e) for e in entries]
    first.close()
    assert ids == sorted(set(ids))

    second = connect(database)
    try:
        reopened = Blacklist(second)
        assert reopened.entries() == entries
        assert [entry_id for entry_id, _ in reopened.rows()] == ids
        assert [e for _, e in reopened.rows()] == entries
    finally:
        second.close()


def test_variant_duplicates_raise_already_blacklisted_and_write_nothing(
    conn: sqlite3.Connection,
) -> None:
    blacklist = Blacklist(conn)
    blacklist.add(_entry(value="Acme Corp"))
    with pytest.raises(AlreadyBlacklisted):
        blacklist.add(_entry(value="ACME Corporation"))
    with pytest.raises(AlreadyBlacklisted):
        blacklist.add(_entry(value=CYRILLIC_A_ACME))
    assert len(blacklist.entries()) == 1
    assert not conn.in_transaction


def test_the_same_value_under_another_kind_is_not_a_duplicate(conn: sqlite3.Connection) -> None:
    blacklist = Blacklist(conn)
    blacklist.add(_entry(BlockReason.SLUG, "acme"))
    blacklist.add(_entry(BlockReason.DOMAIN, "acme"))
    assert len(blacklist.entries()) == 2


def test_remove_deletes_the_entry_and_reports_a_second_removal(conn: sqlite3.Connection) -> None:
    blacklist = Blacklist(conn)
    entry_id = blacklist.add(_entry())
    assert blacklist.remove(entry_id) is True
    assert blacklist.remove(entry_id) is False
    assert blacklist.entries() == []
    assert is_blacklisted(Candidate("Acme Corp", None, None), blacklist.entries()) is None


def test_a_hostile_reason_is_stored_and_returned_as_plain_text(conn: sqlite3.Connection) -> None:
    hostile = "'); DROP TABLE blacklist_entry; -- <script>alert(1)</script>"
    blacklist = Blacklist(conn)
    blacklist.add(
        BlacklistEntry(
            match_kind=BlockReason.COMPANY_KEY, value="Acme Corp", reason=hostile, added_at=ADDED_AT
        )
    )
    assert [e.reason for e in blacklist.entries()] == [hostile]


def test_a_hostile_slug_is_stored_and_returned_as_plain_text(conn: sqlite3.Connection) -> None:
    hostile = "x'; drop table blacklist_entry; --"
    blacklist = Blacklist(conn)
    blacklist.add(_entry(BlockReason.SLUG, hostile))
    assert [e.value for e in blacklist.entries()] == [hostile]


def test_a_blacklist_loaded_from_the_database_blocks_variants(conn: sqlite3.Connection) -> None:
    blacklist = Blacklist(conn)
    blacklist.add(_entry(BlockReason.COMPANY_KEY, "Acme Corp"))
    blacklist.add(_entry(BlockReason.SLUG, "Globex"))
    blacklist.add(_entry(BlockReason.DOMAIN, "initech.com"))
    loaded = blacklist.entries()
    for name in [CYRILLIC_A_ACME, ZERO_WIDTH_ACME, "ACME Corporation"]:
        assert is_blacklisted(Candidate(name, None, None), loaded) is BlockReason.COMPANY_KEY
    assert is_blacklisted(Candidate("Other", " GLOBEX ", None), loaded) is BlockReason.SLUG
    assert (
        is_blacklisted(Candidate("Other", None, "https://WWW.Initech.com/x"), loaded)
        is BlockReason.DOMAIN
    )
    assert is_blacklisted(Candidate("Hooli", "hooli", "hooli.com"), loaded) is None


class SocketCalls:
    def __init__(self) -> None:
        self.attempts: list[str] = []


@pytest.fixture
def socket_guard(monkeypatch: pytest.MonkeyPatch) -> SocketCalls:
    """Replaces the real socket entry points with functions that record and raise."""
    calls = SocketCalls()

    def refuse(name: str) -> Callable[..., NoReturn]:
        def guarded(*args: object, **kwargs: object) -> NoReturn:
            calls.attempts.append(name)
            raise AssertionError(f"network call attempted: {name}")

        return guarded

    monkeypatch.setattr(socket.socket, "connect", refuse("socket.connect"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
    return calls


def test_the_socket_guard_records_a_deliberate_connect(socket_guard: SocketCalls) -> None:
    with pytest.raises(AssertionError):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(AssertionError):
        socket.getaddrinfo("localhost", 80)
    with socket.socket() as sock, pytest.raises(AssertionError):
        sock.connect(("127.0.0.1", 9))
    assert socket_guard.attempts == ["create_connection", "getaddrinfo", "socket.connect"]


def test_the_filter_runs_over_a_stored_blacklist_without_any_network_call(
    conn: sqlite3.Connection, socket_guard: SocketCalls
) -> None:
    blacklist = Blacklist(conn)
    blacklist.add(_entry(BlockReason.COMPANY_KEY, "Acme Corp"))
    blacklist.add(_entry(BlockReason.SLUG, "globex"))
    blacklist.add(_entry(BlockReason.DOMAIN, "initech.com"))
    loaded = blacklist.entries()
    candidates = [
        Candidate("Acme Corp", None, None),
        Candidate(CYRILLIC_A_ACME, None, None),
        Candidate("Other", "globex", None),
        Candidate("Other", None, "initech.com"),
        Candidate("Hooli", "hooli", "hooli.com"),
        Candidate("Hooli", None, None),
    ]
    results = [is_blacklisted(c, loaded) for c in candidates]
    assert results == [
        BlockReason.COMPANY_KEY,
        BlockReason.COMPANY_KEY,
        BlockReason.SLUG,
        BlockReason.DOMAIN,
        None,
        None,
    ]
    assert socket_guard.attempts == []
