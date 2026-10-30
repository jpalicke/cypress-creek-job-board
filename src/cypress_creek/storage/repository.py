# ABOUTME: Small stores for postings and reports over the SQLite database, one connection per call.
# ABOUTME: Rows hold the same models the pipeline uses, so what is read back equals what was saved.
import secrets
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from cypress_creek.ingest.models import Extractor, Posting, PostingSource, PostingWarning
from cypress_creek.pipeline.report import GapReport
from cypress_creek.storage.db import connect, migrate

REPORT_ID_BYTES = 8
_WARNINGS = TypeAdapter(list[PostingWarning])


class StoredVerdict(BaseModel):
    """A validator verdict kept with a report. The offending text is deliberately not kept."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str
    subject: str
    validator: str
    passed: bool
    reason: str


_VERDICTS = TypeAdapter(list[StoredVerdict])


class StoredReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str
    posting_id: str
    created_at: datetime
    report: GapReport
    verdicts: list[StoredVerdict]


def prepare_database(path: Path) -> Path:
    """Create the file if needed and apply every migration. Returns the path for the stores."""
    with closing(connect(path)) as conn:
        migrate(conn)
    return path


class PostingStore:
    def __init__(self, database: Path) -> None:
        self._database = database

    def add(self, posting: Posting) -> None:
        with closing(connect(self._database)) as conn:
            conn.execute(
                "INSERT INTO posting (id, source, text, text_hash, origin_url, extractor_name,"
                " extractor_version, warnings_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    posting.id,
                    posting.source.value,
                    posting.text,
                    posting.text_hash,
                    posting.origin_url,
                    posting.extractor.name,
                    posting.extractor.version,
                    _WARNINGS.dump_json(posting.warnings).decode("utf-8"),
                    posting.created_at.isoformat(),
                ),
            )

    def get(self, posting_id: str) -> Posting | None:
        with closing(connect(self._database)) as conn:
            row = conn.execute(
                "SELECT id, source, text, text_hash, origin_url, extractor_name,"
                " extractor_version, warnings_json, created_at FROM posting WHERE id = ?",
                (posting_id,),
            ).fetchone()
        if row is None:
            return None
        return Posting(
            id=row[0],
            source=PostingSource(row[1]),
            text=row[2],
            text_hash=row[3],
            origin_url=row[4],
            extractor=Extractor(name=row[5], version=row[6]),
            warnings=_WARNINGS.validate_json(row[7]),
            created_at=datetime.fromisoformat(row[8]),
        )


class ReportStore:
    def __init__(self, database: Path) -> None:
        self._database = database

    def add(
        self, report: GapReport, verdicts: list[StoredVerdict], *, now: datetime | None = None
    ) -> str:
        report_id = f"rep-{secrets.token_hex(REPORT_ID_BYTES)}"
        created = (now or datetime.now(UTC)).isoformat()
        with closing(connect(self._database)) as conn:
            conn.execute(
                "INSERT INTO report (id, posting_id, status, report_json, verdicts_json,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report_id,
                    report.posting_id,
                    report.status.value,
                    report.model_dump_json(),
                    _VERDICTS.dump_json(verdicts).decode("utf-8"),
                    created,
                ),
            )
        return report_id

    def get(self, report_id: str) -> StoredReport | None:
        with closing(connect(self._database)) as conn:
            row = conn.execute(
                "SELECT posting_id, report_json, verdicts_json, created_at FROM report"
                " WHERE id = ?",
                (report_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredReport(
            report_id=report_id,
            posting_id=row[0],
            created_at=datetime.fromisoformat(row[3]),
            report=GapReport.model_validate_json(row[1]),
            verdicts=_VERDICTS.validate_json(row[2]),
        )
