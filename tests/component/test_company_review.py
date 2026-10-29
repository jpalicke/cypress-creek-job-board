# ABOUTME: Tests the pending suggestion store, human approval and permanent denial on real SQLite.
# ABOUTME: Approval is the only watchlist write, and a denial is a tombstone the filter honors.
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cypress_creek.discovery.resolver import Resolution
from cypress_creek.discovery.review import NotPending, approve, deny
from cypress_creek.discovery.suggestion_store import AddOutcome, SuggestionStore
from cypress_creek.discovery.suggestions import NameOutcome, filter_names
from cypress_creek.discovery.tombstones import Tombstones
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist
from cypress_creek.storage.db import connect, migrate

NOW = datetime(2024, 6, 1, tzinfo=UTC)
STRONG = Resolution("greenhouse", "globex", IdentityEvidence.STRONG, "Globex Corporation")
WEAK = Resolution("lever", "initech", IdentityEvidence.WEAK, None)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connect(tmp_path / "db.sqlite3")) as connection:
        migrate(connection)
        yield connection


def test_a_pending_suggestion_is_listed_with_its_grade_and_board(conn: sqlite3.Connection) -> None:
    store = SuggestionStore(conn)
    assert store.add_pending("Globex", "qwen3.5:0.8b", STRONG) is AddOutcome.ADDED
    assert store.add_pending("Initech", "qwen3.5:0.8b", WEAK) is AddOutcome.ADDED

    rows = store.pending()

    assert [(r.name, r.ats, r.slug, r.evidence.value) for r in rows] == [
        ("Globex", "greenhouse", "globex", "strong"),
        ("Initech", "lever", "initech", "weak"),
    ]
    assert rows[0].organization_name == "Globex Corporation"
    assert rows[1].organization_name is None
    assert Watchlist(conn).entries() == []


def test_a_repeated_proposal_is_not_queued_twice(conn: sqlite3.Connection) -> None:
    store = SuggestionStore(conn)
    store.add_pending("Globex", "model", STRONG)
    assert store.add_pending("GLOBEX Inc", "model", STRONG) is AddOutcome.ALREADY_PENDING
    assert len(store.pending()) == 1


def test_a_company_already_on_the_watchlist_is_not_proposed_again(conn: sqlite3.Connection) -> None:
    store = SuggestionStore(conn)
    store.add_pending("Globex", "model", STRONG)
    approve(conn, store.pending()[0].id, NOW)

    assert store.add_pending("Globex", "model", STRONG) is AddOutcome.ALREADY_WATCHED
    assert store.add_pending("Other Name", "model", STRONG) is AddOutcome.ALREADY_WATCHED


def test_approval_is_the_only_watchlist_write_and_keeps_the_grade(conn: sqlite3.Connection) -> None:
    store = SuggestionStore(conn)
    store.add_pending("Initech", "model", WEAK)
    suggestion = store.pending()[0]
    assert Watchlist(conn).entries() == []

    entry = approve(conn, suggestion.id, NOW)

    assert (entry.display_name, entry.ats, entry.slug) == ("Initech", "lever", "initech")
    assert entry.identity_evidence is IdentityEvidence.WEAK
    assert entry.approved_at == NOW
    assert [e.company_key for e in Watchlist(conn).entries()] == [entry.company_key]
    assert store.pending() == []


def test_a_suggestion_can_be_decided_only_once(conn: sqlite3.Connection) -> None:
    store = SuggestionStore(conn)
    store.add_pending("Globex", "model", STRONG)
    suggestion_id = store.pending()[0].id
    approve(conn, suggestion_id, NOW)

    with pytest.raises(NotPending):
        approve(conn, suggestion_id, NOW)
    with pytest.raises(NotPending):
        deny(conn, suggestion_id, NOW)
    with pytest.raises(NotPending):
        approve(conn, 9999, NOW)


def test_denial_writes_a_tombstone_by_company_and_board_and_adds_no_watchlist_entry(
    conn: sqlite3.Connection,
) -> None:
    store = SuggestionStore(conn)
    store.add_pending("Globex", "model", STRONG)
    deny(conn, store.pending()[0].id, NOW)

    tombstones = Tombstones(conn)
    assert tombstones.denied_company("GLOBEX Corp") is not None
    assert tombstones.is_denied(name="Somebody Else", ats="greenhouse", slug="globex")
    assert Watchlist(conn).entries() == []
    assert store.pending() == []


def test_a_denied_company_never_comes_back_from_the_model_or_the_store(
    conn: sqlite3.Connection,
) -> None:
    store = SuggestionStore(conn)
    store.add_pending("Globex", "model", STRONG)
    deny(conn, store.pending()[0].id, NOW)

    decisions = filter_names(["Globex", "GLOBEX Corporation"], Tombstones(conn), [])
    assert {d.outcome for d in decisions} == {NameOutcome.DENIED}
    assert store.add_pending("Globex", "model", STRONG) is AddOutcome.DENIED
    other_board = Resolution("ashby", "globex-careers", IdentityEvidence.WEAK, None)
    assert store.add_pending("Globex", "model", other_board) is AddOutcome.DENIED
    same_board = Resolution("greenhouse", "globex", IdentityEvidence.STRONG, "Other")
    assert store.add_pending("Different Name", "model", same_board) is AddOutcome.DENIED


def test_denying_one_board_also_denies_the_companys_other_pending_rows(
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
        "INSERT INTO suggestion (name, company_key, proposed_by, ats, slug, resolver_result,"
        " state) VALUES ('Globex', 'globex', 'model', 'lever', 'globex', '{}', 'pending')"
    )
    store = SuggestionStore(conn)
    store.add_pending("Initech", "model", WEAK)
    first = conn.execute("SELECT id FROM suggestion WHERE company_key = 'globex'").fetchone()[0]

    deny(conn, first, NOW)

    assert [row.name for row in store.pending()] == ["Initech"]


def test_a_denial_is_lifted_only_by_the_explicit_remove_call(conn: sqlite3.Connection) -> None:
    store = SuggestionStore(conn)
    store.add_pending("Globex", "model", STRONG)
    deny(conn, store.pending()[0].id, NOW)

    assert filter_names(["Globex"], Tombstones(conn), [])[0].outcome is NameOutcome.DENIED
    Tombstones(conn).remove(name="Globex")
    assert filter_names(["Globex"], Tombstones(conn), [])[0].outcome is NameOutcome.ACCEPTED
