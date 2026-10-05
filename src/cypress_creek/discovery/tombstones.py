# ABOUTME: Permanent tombstones for companies a human denied, kept as denied suggestion rows.
# ABOUTME: Only an explicit remove call lifts one. A company is matched by key and by board.
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from cypress_creek.storage.company_key import company_key


class InvalidBoard(ValueError):
    """A board needs both an ATS and a slug, neither empty."""


class DenialReason(StrEnum):
    COMPANY = "company"
    BOARD = "board"


@dataclass(frozen=True)
class Denial:
    """Why a company or board is blocked, and the name that was denied."""

    reason: DenialReason
    name: str


def normalize_board(ats: str, slug: str) -> tuple[str, str]:
    """The one board normalizer: trimmed and lower case. Raises InvalidBoard on an empty part."""
    ats_part, slug_part = ats.strip().lower(), slug.strip().lower()
    if not ats_part or not slug_part:
        raise InvalidBoard(f"a board needs an ATS and a slug: {ats!r}, {slug!r}")
    return ats_part, slug_part


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
        """Record a human denial. Denying the same company on the same board again is a no-op."""
        if (ats is None) != (slug is None):
            raise InvalidBoard(
                f"a denial needs both an ATS and a slug or neither: {ats!r}, {slug!r}"
            )
        board = None if ats is None or slug is None else normalize_board(ats, slug)
        self._conn.execute(
            "INSERT OR IGNORE INTO suggestion"
            " (name, company_key, proposed_by, ats, slug, resolver_result, state, decided_at)"
            " VALUES (?, ?, ?, ?, ?, '{}', 'denied', ?)",
            (
                name,
                company_key(name),
                proposed_by,
                *(board or (None, None)),
                decided_at.isoformat(),
            ),
        )

    def denial(self, *, name: str, ats: str, slug: str) -> Denial | None:
        """Why this company or board is denied, or None. The company match is checked first."""
        ats, slug = normalize_board(ats, slug)
        by_company = self._conn.execute(
            "SELECT name FROM suggestion WHERE state = 'denied' AND company_key = ?",
            (company_key(name),),
        ).fetchone()
        if by_company:
            return Denial(DenialReason.COMPANY, by_company[0])
        by_board = self._conn.execute(
            "SELECT name FROM suggestion WHERE state = 'denied' AND ats = ? AND slug = ?",
            (ats, slug),
        ).fetchone()
        if by_board:
            return Denial(DenialReason.BOARD, by_board[0])
        return None

    def is_denied(self, *, name: str, ats: str, slug: str) -> bool:
        return self.denial(name=name, ats=ats, slug=slug) is not None

    def remove(self, *, name: str) -> int:
        """The human removal of a company's tombstones, on every board. Returns how many."""
        removed = self._conn.execute(
            "DELETE FROM suggestion WHERE state = 'denied' AND company_key = ?",
            (company_key(name),),
        )
        return removed.rowcount
