# ABOUTME: Live test of a discovery run: a real adapter, real SQLite and a real Ollama model.
# ABOUTME: An unreachable server fails loudly, this test is never skipped.
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from http_support import http_server, local_target

from cypress_creek.config import parse_settings
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.filters import ListingFilters
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.discovery.run import RunIdentity, ScoreStatus, run_discovery
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.ingest.models import Posting
from cypress_creek.ingest.safe_http import FetchResponse, _fetch
from cypress_creek.pipeline.report import TRIAGE_DISCLAIMER, GapReport, verify_report
from cypress_creek.pipeline.run import analyze
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.storage.db import connect, migrate

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
FIXTURE = Path(__file__).parent.parent / "fixtures" / "lever" / "palantir_page.json"
SLUG = "examplecoboard"
NOW = datetime(2026, 3, 31, 12, tzinfo=UTC)
TODAY = date(2026, 3, 31)
BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 3 years.
    kind: project
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
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


def _live_fetch(
    url: str, *, limits: Any, if_none_match: str | None, pass_through_statuses: bool
) -> FetchResponse:
    return _fetch(
        url,
        limits,
        resolve=local_target,
        if_none_match=if_none_match,
        pass_through_statuses=pass_through_statuses,
    )


def test_a_run_over_recorded_postings_scores_them_with_a_real_model_and_reuses_the_scores(
    tmp_path: Path,
) -> None:
    bank_path = tmp_path / "bank.yaml"
    bank_path.write_text(BANK, encoding="utf8")
    bank = load_bank(bank_path)
    provider = OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 8192}
        )
    )
    calls: list[str] = []

    def analyzer(posting: Posting) -> GapReport:
        calls.append(posting.id)
        return analyze(posting, bank, provider, backend="ollama", model=MODEL, today=TODAY)

    clock = SystemClock()
    conn = connect(tmp_path / "app.sqlite3")
    try:
        migrate(conn)
        Watchlist(conn).add(WatchlistEntry("Example Co", "lever", SLUG, IdentityEvidence.WEAK, NOW))
        identity = RunIdentity(bank_hash(bank), "ollama", MODEL)
        routes = {f"/us/{SLUG}?mode=json&limit=100&skip=0": FIXTURE.read_bytes()}
        with http_server(routes) as (port, _):
            base = f"http://fixture.test:{port}"
            client = PoliteClient(
                FetchPolicy(),
                ResponseCache(tmp_path / "cache"),
                HostRateLimiter(clock, delay_seconds=0.0),
                clock,
                limits=LEVER_FETCH_LIMITS,
                fetch=_live_fetch,
            )
            adapter = LeverAdapter(client, us_base_url=f"{base}/us", eu_base_url=f"{base}/eu")
            adapters = {"lever": adapter}
            first = run_discovery(
                conn, adapters, [], ListingFilters(), analyzer, identity, today=TODAY, now=NOW
            )
            calls_after_first = len(calls)
            second = run_discovery(
                conn, adapters, [], ListingFilters(), analyzer, identity, today=TODAY, now=NOW
            )
        total = len(json.loads(FIXTURE.read_text(encoding="utf-8")))
        assert len(first.ranked) == total
        assert first.summary.scored + first.summary.unscored == total
        for row in first.ranked:
            if row.status is ScoreStatus.UNSCORED:
                continue
            assert row.run_id is not None
            (stored,) = conn.execute(
                "SELECT report_json FROM discovery_report WHERE run_id = ?", (row.run_id,)
            ).fetchone()
            report = GapReport.model_validate_json(stored)
            verify_report(report, bank)
            assert report.score_disclaimer == TRIAGE_DISCLAIMER
        # A complete score is reused with no model call. An incomplete one is tried again.
        assert second.summary.cache_hits + second.summary.scored + second.summary.unscored == total
        assert len(calls) - calls_after_first == second.summary.scored
    finally:
        conn.close()
