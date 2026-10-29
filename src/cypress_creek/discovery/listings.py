# ABOUTME: The listing table repository and its state transitions: new, seen and closed.
# ABOUTME: Only a successful fetch of a whole board changes states, so a failed one closes nothing.
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from cypress_creek.discovery.adapters.base import (
    BoardAdapter,
    BoardFetch,
    Listing,
    ListingState,
    listing_id,
)
from cypress_creek.discovery.tombstones import normalize_board

_COLUMNS = (
    "id, ats, slug, title, location, url, posted_at, fetched_at, content_text, content_hash, state"
)


@dataclass(frozen=True)
class StateChanges:
    """How many listings of one board a fetch added, kept as seen, and closed."""

    added: int
    seen: int
    closed: int


class Listings:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def refresh(self, adapter: BoardAdapter, ats: str, slug: str) -> StateChanges:
        """Fetch a board and apply it. A fetch that raises changes nothing."""
        return self.apply_fetch(ats, slug, adapter.fetch_board(slug))

    def apply_fetch(self, ats: str, slug: str, fetch: BoardFetch) -> StateChanges:
        """Apply one successful fetch of a whole board in one transaction.

        A listing in the fetch is stored as new when unknown, and as seen when known (a closed
        listing that returns is seen again). A stored listing of this board that is not in the
        fetch becomes closed, except when the fetch skipped a job it could not read. A skipped job
        with a known id protects that listing, and a skipped job with no id protects the whole
        board, because it may have been any of them. Raises ValueError, writing nothing, when a
        listing belongs to another board.
        """
        board = normalize_board(ats, slug)
        for listing in fetch.listings:
            if normalize_board(listing.ats, listing.slug) != board:
                raise ValueError("a listing belongs to a different board")
        fetched = {listing.id for listing in fetch.listings}
        protected = {
            listing_id(board[0], board[1], skipped.job_id)
            for skipped in fetch.skipped
            if skipped.job_id is not None
        }
        close_absent = all(skipped.job_id is not None for skipped in fetch.skipped)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            added = seen = 0
            known = {
                row[0]
                for row in self._conn.execute(
                    "SELECT id FROM listing WHERE ats = ? AND slug = ?", board
                )
            }
            for listing in fetch.listings:
                if listing.id in known:
                    self._update(listing)
                    seen += 1
                else:
                    self._insert(listing)
                    added += 1
            closed = 0
            if close_absent:
                for (stale_id,) in self._conn.execute(
                    "SELECT id FROM listing WHERE ats = ? AND slug = ? AND state <> 'closed'",
                    board,
                ).fetchall():
                    if stale_id not in fetched and stale_id not in protected:
                        self._conn.execute(
                            "UPDATE listing SET state = 'closed' WHERE id = ?", (stale_id,)
                        )
                        closed += 1
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        return StateChanges(added=added, seen=seen, closed=closed)

    def board(self, ats: str, slug: str) -> list[Listing]:
        """Every stored listing of a board, ordered by id."""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM listing WHERE ats = ? AND slug = ? ORDER BY id",
            normalize_board(ats, slug),
        ).fetchall()
        return [
            Listing(
                id=row[0],
                ats=row[1],
                slug=row[2],
                title=row[3],
                location=row[4],
                url=row[5],
                posted_at=datetime.fromisoformat(row[6]) if row[6] else None,
                fetched_at=datetime.fromisoformat(row[7]),
                content_text=row[8],
                content_hash=row[9],
                state=ListingState(row[10]),
            )
            for row in rows
        ]

    def _insert(self, listing: Listing) -> None:
        self._conn.execute(
            f"INSERT INTO listing ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*_fields(listing), ListingState.NEW.value),
        )

    def _update(self, listing: Listing) -> None:
        self._conn.execute(
            "UPDATE listing SET ats = ?, slug = ?, title = ?, location = ?, url = ?,"
            " posted_at = ?, fetched_at = ?, content_text = ?, content_hash = ?, state = ?"
            " WHERE id = ?",
            (*_fields(listing)[1:], ListingState.SEEN.value, listing.id),
        )


def _fields(listing: Listing) -> tuple[str, str, str, str, str, str, str | None, str, str, str]:
    return (
        listing.id,
        listing.ats,
        listing.slug,
        listing.title,
        listing.location,
        listing.url,
        listing.posted_at.isoformat() if listing.posted_at else None,
        listing.fetched_at.isoformat(),
        listing.content_text,
        listing.content_hash,
    )
