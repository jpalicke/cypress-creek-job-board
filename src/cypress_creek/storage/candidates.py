# ABOUTME: Pending facts proposed from a resume, kept in SQLite apart from the fact bank.
# ABOUTME: A candidate changes state only from pending, once, and a state is never verified.
import json
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Kind
from cypress_creek.pipeline.resume_import import Candidate, claim_key
from cypress_creek.storage.db import connect

CANDIDATE_ID_BYTES = 8
State = Literal["pending", "approved", "rejected"]


class StoredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    claim: str
    kind: Kind
    tags: list[str]
    source: str
    state: State
    resume_hash: str
    created_at: datetime
    decided_at: datetime | None
    fact_id: str | None


class CandidateNotPending(Exception):
    """The candidate is unknown or was already approved or rejected."""


_COLUMNS = "id, claim, kind, tags_json, source, state, resume_hash, created_at, decided_at, fact_id"


def _row(row: tuple[object, ...]) -> StoredCandidate:
    return StoredCandidate(
        id=str(row[0]),
        claim=str(row[1]),
        kind=Kind(str(row[2])),
        tags=json.loads(str(row[3])),
        source=str(row[4]),
        state=str(row[5]),  # type: ignore[arg-type]
        resume_hash=str(row[6]),
        created_at=datetime.fromisoformat(str(row[7])),
        decided_at=datetime.fromisoformat(str(row[8])) if row[8] else None,
        fact_id=str(row[9]) if row[9] else None,
    )


class CandidateStore:
    def __init__(self, database: Path) -> None:
        self._database = database

    def add_all(self, resume_hash: str, candidates: list[Candidate]) -> list[StoredCandidate]:
        """Store each candidate as pending, except one whose claim is already pending."""
        stored: list[StoredCandidate] = []
        with closing(connect(self._database)) as conn, conn:
            pending = {
                str(key)
                for (key,) in conn.execute(
                    "SELECT claim_key FROM fact_candidate WHERE state = 'pending'"
                )
            }
            for candidate in candidates:
                key = claim_key(candidate.claim)
                if key in pending:
                    continue
                pending.add(key)
                new_id = "C-" + secrets.token_hex(CANDIDATE_ID_BYTES)
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    "INSERT INTO fact_candidate (id, resume_hash, claim, claim_key, kind,"
                    " tags_json, source, state, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                    (
                        new_id,
                        resume_hash,
                        candidate.claim,
                        key,
                        candidate.kind.value,
                        json.dumps(candidate.tags),
                        candidate.source,
                        now,
                    ),
                )
                stored.append(self.get_in(conn, new_id))
        return stored

    @staticmethod
    def get_in(conn: sqlite3.Connection, candidate_id: str) -> StoredCandidate:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM fact_candidate WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise CandidateNotPending(candidate_id)
        return _row(row)

    def get(self, candidate_id: str) -> StoredCandidate | None:
        with closing(connect(self._database)) as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM fact_candidate WHERE id = ?", (candidate_id,)
            ).fetchone()
        return _row(row) if row else None

    def list(self, state: State | None = None) -> list[StoredCandidate]:
        query = f"SELECT {_COLUMNS} FROM fact_candidate"
        args: tuple[str, ...] = ()
        if state is not None:
            query += " WHERE state = ?"
            args = (state,)
        with closing(connect(self._database)) as conn:
            return [_row(row) for row in conn.execute(query + " ORDER BY created_at, id", args)]

    def decide(self, candidate_id: str, state: State, fact_id: str | None = None) -> None:
        """Move a pending candidate to approved or rejected. Anything else raises."""
        with closing(connect(self._database)) as conn, conn:
            changed = conn.execute(
                "UPDATE fact_candidate SET state = ?, decided_at = ?, fact_id = ?"
                " WHERE id = ? AND state = 'pending'",
                (state, datetime.now(UTC).isoformat(), fact_id, candidate_id),
            ).rowcount
        if changed != 1:
            raise CandidateNotPending(candidate_id)

    def attach_fact(self, candidate_id: str, fact_id: str) -> None:
        with closing(connect(self._database)) as conn, conn:
            conn.execute(
                "UPDATE fact_candidate SET fact_id = ? WHERE id = ? AND state = 'approved'",
                (fact_id, candidate_id),
            )

    def reopen(self, candidate_id: str) -> None:
        """Put an approved candidate back to pending when its fact could not be written."""
        with closing(connect(self._database)) as conn, conn:
            conn.execute(
                "UPDATE fact_candidate SET state = 'pending', decided_at = NULL, fact_id = NULL"
                " WHERE id = ? AND state = 'approved'",
                (candidate_id,),
            )
