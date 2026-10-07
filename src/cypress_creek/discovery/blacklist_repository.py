# ABOUTME: The blacklist table repository: add, list, and remove blocked companies, slugs, domains.
# ABOUTME: The pure matching lives in blacklist.py. This module only stores and loads entries.
import sqlite3
from datetime import datetime

from cypress_creek.discovery.blacklist import BlacklistEntry, BlockReason


class AlreadyBlacklisted(Exception):
    """The same normalized company key, slug or domain is already on the blacklist."""


class Blacklist:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, entry: BlacklistEntry) -> int:
        """Add an entry and return its id. Raises AlreadyBlacklisted without writing."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if self._conn.execute(
                "SELECT 1 FROM blacklist_entry WHERE match_kind = ? AND value = ?",
                (entry.match_kind.value, entry.value),
            ).fetchone():
                raise AlreadyBlacklisted(
                    f"already blacklisted as a {entry.match_kind.value}: {entry.value}"
                )
            cursor = self._conn.execute(
                "INSERT INTO blacklist_entry (match_kind, value, reason, added_at)"
                " VALUES (?, ?, ?, ?)",
                (entry.match_kind.value, entry.value, entry.reason, entry.added_at.isoformat()),
            )
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def remove(self, entry_id: int) -> bool:
        """Remove an entry by id. Returns whether one was there."""
        removed = self._conn.execute("DELETE FROM blacklist_entry WHERE id = ?", (entry_id,))
        return removed.rowcount > 0

    def rows(self) -> list[tuple[int, BlacklistEntry]]:
        """Every entry with its id, oldest first."""
        stored = self._conn.execute(
            "SELECT id, match_kind, value, reason, added_at FROM blacklist_entry ORDER BY id"
        ).fetchall()
        return [
            (
                entry_id,
                BlacklistEntry(
                    match_kind=BlockReason(kind),
                    value=value,
                    reason=reason,
                    added_at=datetime.fromisoformat(added_at),
                ),
            )
            for entry_id, kind, value, reason, added_at in stored
        ]

    def entries(self) -> list[BlacklistEntry]:
        return [entry for _, entry in self.rows()]
