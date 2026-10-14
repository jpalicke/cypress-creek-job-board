# ABOUTME: Persists evaluation runs as ordered JSON records in SQLite transactions.
# ABOUTME: Resume validates the stored header and every event before accepting another row.
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from cypress_creek.eval_records import (
    CaseRecord,
    RunHeader,
    RunState,
    RunTerminal,
    parse_run_rows,
)


class EvalStore:
    """The live source of truth for resumable evaluation runs."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start(self, header: RunHeader) -> None:
        """Create a run, or confirm that an existing run has the same header."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT header_json FROM eval_run WHERE run_id = ?", (header.run_id,)
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO eval_run (run_id, header_json) VALUES (?, ?)",
                    (header.run_id, header.model_dump_json()),
                )
            else:
                parse_run_rows([row[0]], expected_header=header)
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def load(self, header: RunHeader) -> RunState:
        """Rebuild resume state from the validated header and ordered events."""
        return parse_run_rows(self._rows(header.run_id), expected_header=header)

    def append_case(self, header: RunHeader, case: CaseRecord) -> None:
        """Commit one completed case pair, rejecting duplicates and stale identity."""
        self._append(header, case)

    def append_terminal(self, header: RunHeader, terminal: RunTerminal) -> None:
        """Commit a failed or complete terminal only when its state is valid."""
        self._append(header, terminal)

    def export_jsonl(self, header: RunHeader, path: Path) -> None:
        """Write a validated, immutable JSONL snapshot without changing live state."""
        self._conn.execute("BEGIN")
        try:
            rows = self._rows(header.run_id)
            parse_run_rows(rows, expected_header=header)
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                for row in rows:
                    normalized = json.dumps(
                        json.loads(row), ensure_ascii=False, separators=(",", ":")
                    )
                    output.write(normalized.encode("utf-8") + b"\n")
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _rows(self, run_id: str) -> list[str]:
        header_row = self._conn.execute(
            "SELECT header_json FROM eval_run WHERE run_id = ?", (run_id,)
        ).fetchone()
        if header_row is None:
            raise ValueError("eval run not found")
        events = self._conn.execute(
            "SELECT record_json FROM eval_event WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [header_row[0], *(row[0] for row in events)]

    def _append(self, header: RunHeader, record: CaseRecord | RunTerminal) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            parse_run_rows(
                [*self._rows(header.run_id), record.model_dump_json()],
                expected_header=header,
            )
            self._conn.execute(
                "INSERT INTO eval_event (run_id, record_json) VALUES (?, ?)",
                (header.run_id, record.model_dump_json()),
            )
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
