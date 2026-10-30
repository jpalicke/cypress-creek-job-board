# ABOUTME: Runs discovery in separate child processes sharing one SQLite file and one board server.
# ABOUTME: The second process finds every score stored by the first, so it makes no scoring calls.
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from http_support import http_server

TESTS_DIR = Path(__file__).parent.parent
FIXTURE = TESTS_DIR / "fixtures" / "lever" / "palantir_page.json"
RECORDED: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
SLUG = "examplecoboard"
PATH = f"/us/{SLUG}?mode=json&limit=100&skip=0"
BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 4 years.
    kind: project
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
"""

# The child runs discovery over a real Lever adapter and the test-only loopback resolver. The
# analyzer is the real pipeline after extraction, over hand written requirements, and it counts
# its calls. The provider points at a closed port, which is fine because no requirement needs it.
CHILD = r"""
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

database, tests_dir, port, cache, bank_path, cap = sys.argv[1:7]
sys.path.insert(0, tests_dir)

from cypress_creek.config import parse_settings
from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.filters import ListingFilters
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.discovery.run import RunIdentity, run_discovery
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind
from cypress_creek.ingest.safe_http import _fetch
from cypress_creek.pipeline.extract import ExtractionResult, ExtractionStatus
from cypress_creek.pipeline.run import assess
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.base import Usage
from cypress_creek.storage.db import connect, migrate
from http_support import local_target

now = datetime(2026, 3, 31, 12, tzinfo=UTC)


def live_fetch(url, *, limits, if_none_match, pass_through_statuses):
    return _fetch(
        url,
        limits,
        resolve=local_target,
        if_none_match=if_none_match,
        pass_through_statuses=pass_through_statuses,
    )


clock = SystemClock()
client = PoliteClient(
    FetchPolicy(),
    ResponseCache(Path(cache)),
    HostRateLimiter(clock, delay_seconds=0.0),
    clock,
    limits=LEVER_FETCH_LIMITS,
    fetch=live_fetch,
)
base = "http://fixture.test:" + port
adapter = LeverAdapter(client, us_base_url=base + "/us", eu_base_url=base + "/eu")
bank = load_bank(Path(bank_path))
provider = OllamaProvider(
    parse_settings({"provider": "ollama", "model": "m", "base_url": "http://127.0.0.1:9"})
)
requirement = Requirement(
    id="R-1", text="Needs kubernetes.", span=(0, 10), kind=RequirementKind.SKILL,
    term="kubernetes", importance=Importance.REQUIRED,
)
extraction = ExtractionResult(
    status=ExtractionStatus.OK, requirements=[requirement], dropped=[], not_assessed_count=0,
    failure=None, usage=Usage(input_tokens=1, output_tokens=1), prompt_hash="a" * 64,
    schema_version=1,
)
calls = []


def analyzer(posting):
    calls.append(posting.id)
    return assess(
        posting, extraction, bank, provider, backend="ollama", model="m", today=date(2026, 3, 31)
    )


conn = connect(Path(database))
migrate(conn)
watchlist = Watchlist(conn)
if not watchlist.entries():
    entry = WatchlistEntry("Example Co", "lever", "examplecoboard", IdentityEvidence.WEAK, now)
    watchlist.add(entry)
identity = RunIdentity(bank_hash(bank), "ollama", "m")
result = run_discovery(
    conn, {"lever": adapter}, [], ListingFilters(), analyzer, identity,
    cap=int(cap), today=date(2026, 3, 31), now=now,
)
s = result.summary
print(json.dumps({
    "calls": len(calls), "scored": s.scored, "cache_hits": s.cache_hits,
    "unscored": s.unscored, "stopped_by": s.stopped_by, "rows": len(result.ranked),
}))
conn.close()
"""


def _board(count: int) -> dict[str, bytes]:
    postings = []
    for number in range(count):
        posting = json.loads(json.dumps(RECORDED[number % len(RECORDED)]))
        posting["id"] = f"posting-{number}"
        posting["hostedUrl"] = f"https://jobs.example.test/{SLUG}/posting-{number}"
        posting["text"] = f"Engineer {number}"
        posting["descriptionPlain"] = f"Build things, unit {number}."
        posting["description"] = f"<p>Build things, unit {number}.</p>"
        posting["lists"] = []
        posting["additional"] = ""
        postings.append(posting)
    return {PATH: json.dumps(postings).encode("utf-8")}


def _discover(database: Path, port: int, tmp_path: Path, tag: str, cap: int) -> dict[str, object]:
    bank = tmp_path / "bank.yaml"
    bank.write_text(BANK, encoding="utf8")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD,
            str(database),
            str(TESTS_DIR),
            str(port),
            str(tmp_path / f"cache-{tag}"),
            str(bank),
            str(cap),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


def test_a_second_process_finds_every_score_the_first_one_stored(tmp_path: Path) -> None:
    database = tmp_path / "app.sqlite3"
    with http_server(_board(6)) as (port, _):
        first = _discover(database, port, tmp_path, "one", cap=30)
        second = _discover(database, port, tmp_path, "two", cap=30)
    assert first == {
        "calls": 6,
        "scored": 6,
        "cache_hits": 0,
        "unscored": 0,
        "stopped_by": None,
        "rows": 6,
    }
    assert second["calls"] == 0
    assert second["cache_hits"] == 6
    assert second["scored"] == 0
    assert second["rows"] == 6


def test_a_capped_process_leaves_the_rest_for_the_next_one(tmp_path: Path) -> None:
    database = tmp_path / "app.sqlite3"
    with http_server(_board(6)) as (port, _):
        first = _discover(database, port, tmp_path, "one", cap=4)
        second = _discover(database, port, tmp_path, "two", cap=4)
    assert (first["calls"], first["unscored"], first["stopped_by"]) == (4, 2, "cap")
    assert (second["calls"], second["cache_hits"], second["unscored"]) == (2, 4, 0)
    assert second["stopped_by"] is None
