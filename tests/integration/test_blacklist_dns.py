# ABOUTME: Proves blacklist decisions never reach the real DNS resolver while real DNS is available.
# ABOUTME: A recording passthrough wraps the real getaddrinfo, and the test itself resolves a host.
import socket
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cypress_creek.discovery.blacklist import (
    BlacklistEntry,
    BlockReason,
    Candidate,
    is_blacklisted,
)
from cypress_creek.discovery.blacklist_repository import Blacklist
from cypress_creek.storage.db import connect, migrate

pytestmark = pytest.mark.needs_network

ADDED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "app.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every getaddrinfo host and then calls the real resolver."""
    seen: list[str] = []
    real: Callable[..., Any] = socket.getaddrinfo

    def recording(host: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(str(host))
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", recording)
    return seen


def test_the_recorder_sees_a_real_lookup_so_the_assertion_is_not_vacuous(
    lookups: list[str],
) -> None:
    addresses = socket.getaddrinfo("example.com", 443)
    assert addresses
    assert lookups == ["example.com"]


def test_blacklist_decisions_make_no_dns_lookup_while_dns_is_available(
    conn: sqlite3.Connection, lookups: list[str]
) -> None:
    blacklist = Blacklist(conn)
    blacklist.add(BlacklistEntry(BlockReason.COMPANY_KEY, "Acme Corp", "not a fit", ADDED_AT))
    blacklist.add(BlacklistEntry(BlockReason.SLUG, "globex", "not a fit", ADDED_AT))
    blacklist.add(BlacklistEntry(BlockReason.DOMAIN, "example.com", "not a fit", ADDED_AT))
    loaded = blacklist.entries()

    results = [
        is_blacklisted(Candidate("Аcme Corp", None, None), loaded),
        is_blacklisted(Candidate("\u0410\u0421\u041c\u0415 Corp", None, None), loaded),
        is_blacklisted(Candidate("Other", "GLOBEX", None), loaded),
        is_blacklisted(Candidate("Other", None, "https://www.example.com/jobs"), loaded),
        is_blacklisted(Candidate("Hooli", "hooli", "hooli.example"), loaded),
    ]

    assert results == [
        BlockReason.COMPANY_KEY,
        BlockReason.COMPANY_KEY,
        BlockReason.SLUG,
        BlockReason.DOMAIN,
        None,
    ]
    assert lookups == []
    # The blocked domain is a real, resolvable host: the filter decided without resolving it.
    assert socket.getaddrinfo("example.com", 443)
    assert lookups == ["example.com"]
