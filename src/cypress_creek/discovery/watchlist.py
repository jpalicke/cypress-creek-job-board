# ABOUTME: The watchlist of approved companies, with a guard that refuses denied or duplicate ones.
# ABOUTME: Written only by a human approval, so callers pass the approval time in.
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from cypress_creek.discovery.tombstones import Tombstones
from cypress_creek.storage.company_key import company_key


class IdentityEvidence(StrEnum):
    STRONG = "strong"
    WEAK = "weak"
    NONE = "none"


class Tombstoned(Exception):
    """The company or board was denied by a human and has not been removed from the tombstones."""


class AlreadyWatched(Exception):
    """The company or board is already on the watchlist."""


@dataclass(frozen=True)
class WatchlistEntry:
    """An approved company. Its key is derived from the display name, never supplied."""

    display_name: str
    ats: str
    slug: str
    identity_evidence: IdentityEvidence
    approved_at: datetime
    company_key: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "company_key", company_key(self.display_name))


class Watchlist:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, entry: WatchlistEntry) -> None:
        """Add an approved company. Raises Tombstoned or AlreadyWatched without writing."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._refuse_if_blocked(entry)
            self._conn.execute(
                "INSERT INTO watchlist_entry"
                " (company_key, display_name, ats, slug, identity_evidence, approved_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry.company_key,
                    entry.display_name,
                    entry.ats,
                    entry.slug,
                    entry.identity_evidence.value,
                    entry.approved_at.isoformat(),
                ),
            )
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _refuse_if_blocked(self, entry: WatchlistEntry) -> None:
        reason = Tombstones(self._conn).denial_reason(
            name=entry.display_name, ats=entry.ats, slug=entry.slug
        )
        if reason is not None:
            raise Tombstoned(f"the {reason.value} was denied by a human: {entry.display_name}")
        if self._conn.execute(
            "SELECT 1 FROM watchlist_entry WHERE company_key = ?", (entry.company_key,)
        ).fetchone():
            raise AlreadyWatched(f"company already on the watchlist: {entry.display_name}")
        if self._conn.execute(
            "SELECT 1 FROM watchlist_entry WHERE ats = ? AND slug = ?", (entry.ats, entry.slug)
        ).fetchone():
            raise AlreadyWatched(f"board already on the watchlist: {entry.ats}/{entry.slug}")

    def remove(self, key: str) -> bool:
        """Remove an entry by company key. Returns whether one was there."""
        removed = self._conn.execute("DELETE FROM watchlist_entry WHERE company_key = ?", (key,))
        return removed.rowcount > 0

    def entries(self) -> list[WatchlistEntry]:
        rows = self._conn.execute(
            "SELECT display_name, ats, slug, identity_evidence, approved_at"
            " FROM watchlist_entry ORDER BY company_key"
        ).fetchall()
        return [
            WatchlistEntry(
                display_name=name,
                ats=ats,
                slug=slug,
                identity_evidence=IdentityEvidence(evidence),
                approved_at=datetime.fromisoformat(approved_at),
            )
            for name, ats, slug, evidence, approved_at in rows
        ]
