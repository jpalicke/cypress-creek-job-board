# ABOUTME: Human review of a pending company suggestion: approve it onto the watchlist, or deny it.
# ABOUTME: Approval is the only watchlist write in the suggestion flow, and a denial is permanent.
import sqlite3
from datetime import datetime

from cypress_creek.discovery.suggestion_store import SuggestionStore
from cypress_creek.discovery.watchlist import AlreadyWatched, Watchlist, WatchlistEntry


class NotPending(Exception):
    """The suggestion does not exist or has already been decided."""


def approve(conn: sqlite3.Connection, suggestion_id: int, approved_at: datetime) -> WatchlistEntry:
    """Put the company on the watchlist and mark the suggestion approved.

    The watchlist refuses a company or board that is denied or already watched. If a crash left
    the entry in place before the suggestion was marked, the retry finishes the marking."""
    suggestion = SuggestionStore(conn).get_pending(suggestion_id)
    if suggestion is None:
        raise NotPending(f"suggestion {suggestion_id} is not pending")
    entry = WatchlistEntry(
        display_name=suggestion.name,
        ats=suggestion.ats,
        slug=suggestion.slug,
        identity_evidence=suggestion.evidence,
        approved_at=approved_at,
    )
    try:
        Watchlist(conn).add(entry)
    except AlreadyWatched:
        if not any(e.company_key == entry.company_key for e in Watchlist(conn).entries()):
            raise
    conn.execute(
        "UPDATE suggestion SET state = 'approved', decided_at = ? WHERE id = ?",
        (approved_at.isoformat(), suggestion_id),
    )
    return entry


def deny(conn: sqlite3.Connection, suggestion_id: int, decided_at: datetime) -> None:
    """Deny the company for good. Its other pending boards are denied with it, so the company
    cannot come back through another board. Only an explicit tombstone removal lifts this."""
    row = conn.execute(
        "SELECT company_key FROM suggestion WHERE id = ? AND state = 'pending'", (suggestion_id,)
    ).fetchone()
    if row is None:
        raise NotPending(f"suggestion {suggestion_id} is not pending")
    conn.execute(
        "UPDATE suggestion SET state = 'denied', decided_at = ?"
        " WHERE state = 'pending' AND company_key = ?",
        (decided_at.isoformat(), row[0]),
    )
