# ABOUTME: The pending company suggestions: queued by the suggestion flow, decided by a human.
# ABOUTME: It only reads the watchlist and tombstones. It never writes either, review.py does.
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from cypress_creek.discovery.evidence import IdentityEvidence
from cypress_creek.discovery.resolver import Resolution
from cypress_creek.discovery.tombstones import Tombstones
from cypress_creek.storage.company_key import company_key


class AddOutcome(StrEnum):
    ADDED = "added"
    DENIED = "denied"
    ALREADY_PENDING = "already_pending"
    ALREADY_WATCHED = "already_watched"


@dataclass(frozen=True)
class PendingSuggestion:
    id: int
    name: str
    proposed_by: str
    ats: str
    slug: str
    evidence: IdentityEvidence
    organization_name: str | None


class SuggestionStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add_pending(self, name: str, proposed_by: str, resolution: Resolution) -> AddOutcome:
        """Queue a resolved company for review, unless it is denied, queued or already watched."""
        key = company_key(name)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            outcome = self._refusal(name, key, resolution)
            if outcome is None:
                self._conn.execute(
                    "INSERT INTO suggestion (name, company_key, proposed_by, ats, slug,"
                    " resolver_result, state) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                    (
                        name,
                        key,
                        proposed_by,
                        resolution.ats,
                        resolution.slug,
                        json.dumps(
                            {
                                "evidence": resolution.evidence.value,
                                "organization_name": resolution.organization_name,
                            }
                        ),
                    ),
                )
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        return outcome or AddOutcome.ADDED

    def _refusal(self, name: str, key: str, resolution: Resolution) -> AddOutcome | None:
        denial = Tombstones(self._conn).denial(name=name, ats=resolution.ats, slug=resolution.slug)
        if denial is not None:
            return AddOutcome.DENIED
        if self._conn.execute(
            "SELECT 1 FROM watchlist_entry WHERE company_key = ? OR (ats = ? AND slug = ?)",
            (key, resolution.ats, resolution.slug),
        ).fetchone():
            return AddOutcome.ALREADY_WATCHED
        if self._conn.execute(
            "SELECT 1 FROM suggestion WHERE state = 'pending' AND company_key = ?", (key,)
        ).fetchone():
            return AddOutcome.ALREADY_PENDING
        return None

    def pending(self) -> list[PendingSuggestion]:
        rows = self._conn.execute(
            "SELECT id, name, proposed_by, ats, slug, resolver_result FROM suggestion"
            " WHERE state = 'pending' ORDER BY id"
        ).fetchall()
        return [_pending(*row) for row in rows]

    def get_pending(self, suggestion_id: int) -> PendingSuggestion | None:
        row = self._conn.execute(
            "SELECT id, name, proposed_by, ats, slug, resolver_result FROM suggestion"
            " WHERE state = 'pending' AND id = ?",
            (suggestion_id,),
        ).fetchone()
        return _pending(*row) if row else None


def _pending(
    suggestion_id: int, name: str, proposed_by: str, ats: str, slug: str, stored: str
) -> PendingSuggestion:
    detail = json.loads(stored)
    return PendingSuggestion(
        id=suggestion_id,
        name=name,
        proposed_by=proposed_by,
        ats=ats,
        slug=slug,
        evidence=IdentityEvidence(detail["evidence"]),
        organization_name=detail["organization_name"],
    )
