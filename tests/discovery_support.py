# ABOUTME: Shared helpers for discovery tests: recorded Lever postings served by a loopback server.
# ABOUTME: The adapter is the real LeverAdapter and polite client; only the clock is manual.
import copy
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from http_support import local_target

from cypress_creek.config import parse_settings
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.models import Importance, Posting, Requirement, RequirementKind
from cypress_creek.ingest.safe_http import FetchResponse, _fetch
from cypress_creek.pipeline.extract import ExtractionResult, ExtractionStatus
from cypress_creek.pipeline.report import GapReport
from cypress_creek.pipeline.run import assess
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.base import Usage

FIXTURE = Path(__file__).parent / "fixtures" / "lever" / "palantir_page.json"
RECORDED: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
SLUG = "examplecoboard"


def posting_json(number: int, slug: str = SLUG, note: str = "") -> dict[str, Any]:
    """A posting shaped like a recorded one, with its own id and its own text."""
    posting = copy.deepcopy(RECORDED[number % len(RECORDED)])
    posting["id"] = f"posting-{number}"
    posting["hostedUrl"] = f"https://jobs.example.test/{slug}/posting-{number}"
    posting["text"] = f"Engineer {number}"
    posting["descriptionPlain"] = f"Build things, unit {number}. {note}"
    posting["description"] = f"<p>Build things, unit {number}. {note}</p>"
    posting["lists"] = []
    posting["additional"] = ""
    posting["createdAt"] = 1_760_000_000_000 + number * 86_400_000
    return posting


def lever_routes(count: int, slug: str = SLUG, note: str = "") -> dict[str, bytes]:
    postings = [posting_json(number, slug, note) for number in range(count)]
    return {f"/us/{slug}?mode=json&limit=100&skip=0": json.dumps(postings).encode("utf-8")}


def live_fetch(
    url: str, *, limits: Any, if_none_match: str | None, pass_through_statuses: bool
) -> FetchResponse:
    return _fetch(
        url,
        limits,
        resolve=local_target,
        if_none_match=if_none_match,
        pass_through_statuses=pass_through_statuses,
    )


def lever_adapter(tmp_path: Path, port: int) -> LeverAdapter:
    clock = ManualClock(wall_start=1_760_000_000.0)
    client = PoliteClient(
        FetchPolicy(),
        ResponseCache(tmp_path / "cache"),
        HostRateLimiter(clock, delay_seconds=1.0),
        clock,
        limits=LEVER_FETCH_LIMITS,
        fetch=live_fetch,
        random_source=lambda: 0.0,
    )
    base = f"http://fixture.test:{port}"
    return LeverAdapter(client, us_base_url=f"{base}/us", eu_base_url=f"{base}/eu")


TODAY = date(2026, 3, 31)
NOW = datetime(2026, 3, 31, 12, tzinfo=UTC)
NOTHING_LISTENING = "http://127.0.0.1:9"
BACKEND = "ollama"
MODEL = "qwen3.5:0.8b"
BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 4 years.
    kind: project
    start: 2019-01-01
    end: 2023-01-01
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
"""


def no_sleep(_seconds: float) -> None:
    return None


def provider() -> OllamaProvider:
    return OllamaProvider(
        parse_settings({"provider": BACKEND, "model": MODEL, "base_url": NOTHING_LISTENING})
    )


def extraction(terms: list[str]) -> ExtractionResult:
    requirements = [
        Requirement(
            id=f"R-{index}",
            text=f"Needs {term}.",
            span=(0, 10),
            kind=RequirementKind.SKILL,
            term=term,
            importance=Importance.REQUIRED,
        )
        for index, term in enumerate(terms, start=1)
    ]
    return ExtractionResult(
        status=ExtractionStatus.OK,
        requirements=requirements,
        dropped=[],
        not_assessed_count=0,
        failure=None,
        usage=Usage(input_tokens=500, output_tokens=60),
        prompt_hash="a" * 64,
        schema_version=1,
    )


class Scorer:
    """Scores a posting from recorded requirements and counts calls.

    The requirements are hand written inputs in place of a live extraction. Everything after
    extraction (retrieval, entailment, score, report, citation checks) is the real pipeline."""

    def __init__(self, bank: Bank, terms: list[str] | None = None) -> None:
        self.bank = bank
        self.terms = ["kubernetes"] if terms is None else terms
        self.calls: list[str] = []

    def __call__(self, posting: Posting) -> GapReport:
        self.calls.append(posting.id)
        return assess(
            posting,
            extraction(self.terms),
            self.bank,
            provider(),
            backend=BACKEND,
            model=MODEL,
            today=TODAY,
            sleep=no_sleep,
        )
