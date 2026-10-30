# ABOUTME: Seeds the UI end to end tests with stored reports, including one full of hostile markup.
# ABOUTME: Run by the Playwright web server before the API starts; writes the ids to fixtures.json.
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.ingest.normalize import text_hash
from cypress_creek.pipeline.report import GapReport
from cypress_creek.storage.db import data_dir, database_path
from cypress_creek.storage.repository import (
    PostingStore,
    ReportStore,
    StoredVerdict,
    prepare_database,
)

SCRIPT = "<script>window.__xss = 1; alert(1)</script>"
IMAGE = '<img src=x onerror="window.__xss = 2; alert(2)">'
HOSTILE_TEXT = f"Requirements: {SCRIPT} and {IMAGE}"


def _row(requirement_id: str, text: str, support: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "requirement_id": requirement_id,
        "text": text,
        "importance": "required",
        "ceiling": support,
        "support": support,
        "gate": "term_match" if support != "none" else "no_candidate",
        "fact_ids": ["F-0001"] if support != "none" else [],
        "rationale": None,
        "entailment": "confirmed" if support != "none" else "not_needed",
        "not_model_checked": False,
        "failure": None,
    }
    row.update(extra)
    return row


def _report(posting_id: str, rows: list[dict[str, Any]], **extra: Any) -> GapReport:
    base: dict[str, Any] = {
        "posting_id": posting_id,
        "status": "complete",
        "incomplete_reasons": [],
        "rows": rows,
        "gaps": [row["text"] for row in rows if row["support"] == "none"],
        "not_assessed_count": 0,
        "not_assessed": [],
        "dropped": [],
        "warnings": [],
        "score": {
            "score": 58.3,
            "supported": 1,
            "total": 3,
            "counts": {"strong": 1, "partial": 1, "none": 1},
            "inputs": {
                "weights": {
                    "required": 3,
                    "unspecified": 2,
                    "preferred": 1,
                    "strong": 1.0,
                    "partial": 0.5,
                    "none": 0.0,
                },
                "lines": [],
            },
        },
        "score_disclaimer": "triage only, not a probability",
        "rule_only_ids": [],
        "provenance": {
            "backend": "ollama",
            "model": "fixture",
            "run_id": "run-0123456789abcdef",
            "prompt_hashes": {},
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    }
    base.update(extra)
    return GapReport.model_validate(base)


def _posting(posting_id: str, text: str) -> Posting:
    return Posting(
        id=posting_id,
        source=PostingSource.PASTE,
        text=text,
        text_hash=text_hash(text),
        origin_url=None,
        extractor=Extractor(name="paste", version="1"),
        warnings=[],
        created_at=datetime.now(UTC),
    )


def seed(path: Path) -> dict[str, str]:
    prepare_database(path)
    postings, reports = PostingStore(path), ReportStore(path)
    verdicts: list[StoredVerdict] = []
    postings.add(_posting("post-benign", "Needs Python. Needs SQL. Needs Kubernetes."))
    postings.add(_posting("post-hostile", HOSTILE_TEXT))
    postings.add(_posting("post-incomplete", "Needs Python."))
    benign = _report(
        "post-benign",
        [
            _row("R-1", "Needs Python.", "strong", rationale="F-0001 shows Python work."),
            _row("R-2", "Needs SQL.", "partial"),
            _row("R-3", "Needs Kubernetes.", "none"),
        ],
    )
    hostile_rows = [
        _row("R-1", HOSTILE_TEXT, "strong", fact_ids=[SCRIPT], rationale=IMAGE),
        _row("R-2", IMAGE, "none"),
    ]
    hostile = _report(
        "post-hostile",
        hostile_rows,
        gaps=[SCRIPT],
        not_assessed_count=1,
        not_assessed=[{"text": f"Must know {SCRIPT}", "span": [0, 10]}],
        dropped=[{"text": IMAGE, "reason": "text_not_in_posting"}],
        provenance={
            "backend": SCRIPT,
            "model": IMAGE,
            "run_id": "run-0123456789abcdef",
            "prompt_hashes": {},
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    )
    incomplete = _report(
        "post-incomplete",
        [],
        status="incomplete",
        incomplete_reasons=["extraction failed: provider_unavailable"],
        score=None,
    )
    return {
        "benign": reports.add(benign, verdicts),
        "hostile": reports.add(hostile, verdicts),
        "incomplete": reports.add(incomplete, verdicts),
    }


SAMPLE_BANK = Path(__file__).resolve().parents[1] / "evals" / "bank" / "sample_bank.yaml"


def main() -> int:
    # The fact bank screen edits its file, so the tests get their own copy of the fictional bank.
    data_dir().mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SAMPLE_BANK, data_dir() / "bank.yaml")
    ids = seed(database_path())
    target = data_dir() / "fixtures.json"
    target.write_text(json.dumps(ids), encoding="utf-8")
    print(f"seeded {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
