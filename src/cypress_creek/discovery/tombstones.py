# ABOUTME: Permanent tombstones for companies a human denied, kept as denied suggestion rows.
# ABOUTME: Only an explicit remove call lifts one. A company is matched by key and by board.
import sqlite3
from datetime import datetime
from enum import StrEnum

from cypress_creek.storage.company_key import company_key


class DenialReason(StrEnum):
    COMPANY = "company"
    BOARD = "board"


class Tombstones:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def deny(
        self,
        *,
        name: str,
        ats: str | None,
        slug: str | None,
        proposed_by: str,
        decided_at: datetime,
    ) -> None:
        """Record a human denial. A company already denied keeps its first tombstone."""
        self._conn.execute(
            "INSERT OR IGNORE INTO suggestion"
            " (name, company_key, proposed_by, ats, slug, resolver_result, state, decided_at)"
            " VALUES (?, ?, ?, ?, ?, '{}', 'denied', ?)",
            (name, company_key(name), proposed_by, ats, slug, decided_at.isoformat()),
        )

    def denial_reason(self, *, name: str, ats: str, slug: str) -> DenialReason | None:
        """Why this company or board is denied, or None. The company match is checked first."""
        if self._conn.execute(
            "SELECT 1 FROM suggestion WHERE state = 'denied' AND company_key = ?",
            (company_key(name),),
        ).fetchone():
            return DenialReason.COMPANY
        if self._conn.execute(
            "SELECT 1 FROM suggestion WHERE state = 'denied' AND ats = ? AND slug = ?",
            (ats, slug),
        ).fetchone():
            return DenialReason.BOARD
        return None

    def is_denied(self, *, name: str, ats: str, slug: str) -> bool:
        return self.denial_reason(name=name, ats=ats, slug=slug) is not None

    def remove(self, *, name: str) -> int:
        """The human removal of a company's tombstone. Returns how many were removed."""
        removed = self._conn.execute(
            "DELETE FROM suggestion WHERE state = 'denied' AND company_key = ?",
            (company_key(name),),
        )
        return removed.rowcount
