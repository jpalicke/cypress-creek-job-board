# ABOUTME: Live test that a whole run against a real Ollama server gives a safe gap report.
# ABOUTME: An unreachable server fails loudly, this test is never skipped.
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from cypress_creek.config import parse_settings
from cypress_creek.facts import load_bank
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.pipeline.report import TRIAGE_DISCLAIMER, ReportStatus, verify_report
from cypress_creek.pipeline.run import analyze
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.scoring.support import Support

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"
BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 3 years.
    kind: project
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
  - id: F-0002
    claim: Claimed Go work with no verification.
    kind: project
    tags: [{name: go, level: expert}]
    evidence: {type: self_attested, pointer: notes}
    share: shareable
"""


@pytest.fixture(autouse=True)
def real_ollama_with_the_model() -> None:
    """Fail, never skip, when the server or the model is missing."""
    try:
        listing = httpx.get(f"{BASE_URL}/api/tags", timeout=5).json()
    except httpx.HTTPError as error:
        pytest.fail(
            f"Ollama is not reachable at {BASE_URL} ({error}). Start it with `ollama serve`."
        )
    if MODEL not in {model["name"] for model in listing["models"]}:
        pytest.fail(f"Model {MODEL} is not pulled. Run `ollama pull {MODEL}`.")


def test_a_whole_run_gives_a_complete_or_cleanly_incomplete_report_with_no_uncited_claim(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bank.yaml"
    path.write_text(BANK, encoding="utf8")
    bank = load_bank(path)
    text = (FIXTURES / "posting.txt").read_text(encoding="utf-8")
    posting = Posting(
        id="P-1",
        source=PostingSource.PASTE,
        text=text,
        text_hash=text_hash(text),
        extractor=Extractor(name="paste", version="1"),
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    settings = parse_settings(
        {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 4096}
    )
    inner = OllamaProvider(settings)
    tracker = BudgetTracker(Budget(), inner.capabilities.cost_per_mtok)

    report = analyze(posting, bank, BudgetedProvider(inner, tracker), backend="ollama", model=MODEL)

    assert tracker.requests >= 1
    assert report.status in {ReportStatus.COMPLETE, ReportStatus.INCOMPLETE}
    assert (report.status is ReportStatus.INCOMPLETE) == bool(report.incomplete_reasons)
    assert report.score_disclaimer == TRIAGE_DISCLAIMER
    assert report.provenance.model == MODEL
    assert report.provenance.run_id.startswith("run-")
    assert report.provenance.usage.input_tokens > 0
    verify_report(report, bank)
    for row in report.rows:
        assert set(row.fact_ids) <= {"F-0001"}
        assert row.support is Support.NONE or row.fact_ids
