# ABOUTME: Tests the posting and report stores against a real temporary SQLite file and migrations.
# ABOUTME: A stored posting and report must read back equal, and a report needs its posting.
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cypress_creek.ingest.build import build_posting
from cypress_creek.ingest.models import Extractor, PostingSource
from cypress_creek.pipeline.report import GapReport, Provenance, ReportStatus
from cypress_creek.providers.base import Usage
from cypress_creek.scoring.score import ScoreResult  # noqa: F401
from cypress_creek.storage.db import connect, migrate, schema_version
from cypress_creek.storage.repository import (
    PostingStore,
    ReportStore,
    StoredVerdict,
    prepare_database,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def posting(text: str = "A role requiring Python.") -> object:
    return build_posting(
        text,
        PostingSource.LINK,
        Extractor(name="html-text", version="1"),
        origin_url="https://example.com/job",
        now=NOW,
    )


def incomplete_report(posting_id: str) -> GapReport:
    return GapReport(
        posting_id=posting_id,
        status=ReportStatus.INCOMPLETE,
        incomplete_reasons=["extraction failed: provider_unavailable"],
        rows=[],
        gaps=[],
        not_assessed_count=0,
        dropped=[],
        warnings=[],
        score=None,
        score_disclaimer="triage only, not a probability",
        rule_only_ids=[],
        provenance=Provenance(
            backend="ollama",
            model="m",
            run_id="run-0123456789abcdef",
            prompt_hashes={},
            usage=Usage(input_tokens=0, output_tokens=0),
        ),
    )


def test_the_migration_creates_the_posting_and_report_tables(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "db.sqlite3")) as conn:
        applied = migrate(conn)
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert migrate(conn) == []
        assert schema_version(conn) == max(applied)

    assert {"posting", "report"} <= tables


def test_a_posting_reads_back_equal(tmp_path: Path) -> None:
    store = prepare_database(tmp_path / "db.sqlite3")
    stored = posting("Role​ with a hidden character.")

    PostingStore(store).add(stored)  # type: ignore[arg-type]

    assert PostingStore(store).get(stored.id) == stored  # type: ignore[attr-defined]
    assert PostingStore(store).get("post-missing") is None


def test_a_report_reads_back_with_its_verdicts(tmp_path: Path) -> None:
    store = prepare_database(tmp_path / "db.sqlite3")
    stored = posting()
    PostingStore(store).add(stored)  # type: ignore[arg-type]
    report = incomplete_report(stored.id)  # type: ignore[attr-defined]
    verdicts = [
        StoredVerdict(
            stage="report", subject=report.posting_id, validator="V4", passed=True, reason=""
        )
    ]

    report_id = ReportStore(store).add(report, verdicts, now=NOW)
    found = ReportStore(store).get(report_id)

    assert found is not None
    assert found.report == report
    assert found.verdicts == verdicts
    assert found.created_at == NOW
    assert ReportStore(store).get("rep-missing") is None


def test_each_report_gets_its_own_id(tmp_path: Path) -> None:
    store = prepare_database(tmp_path / "db.sqlite3")
    stored = posting()
    PostingStore(store).add(stored)  # type: ignore[arg-type]
    report = incomplete_report(stored.id)  # type: ignore[attr-defined]

    first = ReportStore(store).add(report, [], now=NOW)
    second = ReportStore(store).add(report, [], now=NOW)

    assert first != second
    assert first.startswith("rep-")


def test_a_report_for_a_missing_posting_is_refused_by_the_database(tmp_path: Path) -> None:
    store = prepare_database(tmp_path / "db.sqlite3")

    with pytest.raises(sqlite3.IntegrityError):
        ReportStore(store).add(incomplete_report("post-missing"), [], now=NOW)
