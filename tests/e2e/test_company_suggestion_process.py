# ABOUTME: Runs company suggestion, approval and denial in separate Python processes on one file.
# ABOUTME: A real loopback server plays the boards, and a denial in one run holds in the next.
import json
import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from http_support import http_server

from cypress_creek.storage.db import connect

ROOT = Path(__file__).resolve().parents[2]

CHILD = """
import json
import sys
from datetime import UTC, datetime
from contextlib import closing
from pathlib import Path

from http_support import local_target
from cypress_creek.discovery.adapters.greenhouse import GREENHOUSE_FETCH_LIMITS, GreenhouseAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, ManualClock
from cypress_creek.discovery.resolver import NegativeCache, Resolver
from cypress_creek.discovery.review import approve, deny
from cypress_creek.discovery.suggestion_store import SuggestionStore
from cypress_creek.discovery.suggestions import suggest_from_names
from cypress_creek.discovery.tombstones import Tombstones
from cypress_creek.discovery.watchlist import Watchlist
from cypress_creek.ingest.safe_http import _fetch
from cypress_creek.storage.db import connect, migrate

mode, db, port, cache = sys.argv[1:5]
now = datetime(2024, 6, 1, tzinfo=UTC)

def live_fetch(url, *, limits, if_none_match, pass_through_statuses):
    return _fetch(url, limits, resolve=local_target, if_none_match=if_none_match,
                  pass_through_statuses=pass_through_statuses)

with closing(connect(Path(db))) as conn:
    migrate(conn)
    if mode == "suggest":
        clock = ManualClock(wall_start=1_760_000_000.0)
        client = PoliteClient(FetchPolicy(), ResponseCache(Path(cache)),
                              HostRateLimiter(clock, delay_seconds=1.0), clock,
                              limits=GREENHOUSE_FETCH_LIMITS, fetch=live_fetch,
                              random_source=lambda: 0.0)
        adapters = {"greenhouse": GreenhouseAdapter(client, base_url=f"http://fixture.test:{port}")}
        report = suggest_from_names(
            ["Globex", "Initech", "https://evil.example"],
            tombstones=Tombstones(conn), blacklist=[],
            resolver=Resolver(adapters, NegativeCache(3600, clock.time)),
            store=SuggestionStore(conn), proposed_by="test-model")
        print(json.dumps({r.raw: r.status.value for r in report.results}))
    else:
        first, second = [s.id for s in SuggestionStore(conn).pending()]
        entry = approve(conn, first, now)
        deny(conn, second, now)
        print(json.dumps({"approved": entry.display_name,
                          "watchlist": [e.display_name for e in Watchlist(conn).entries()]}))
"""


def _run(mode: str, db: Path, port: int, cache: Path) -> dict[str, object]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "tests")}
    result = subprocess.run(
        [sys.executable, "-c", CHILD, mode, str(db), str(port), str(cache)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


def test_suggest_approve_deny_and_suggest_again_across_processes(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    routes = {
        "/v1/boards/globex": json.dumps({"name": "Globex", "content": ""}).encode(),
        "/v1/boards/initech": json.dumps({"name": "Initech", "content": ""}).encode(),
    }
    with http_server(routes) as (port, _):
        first = _run("suggest", db, port, tmp_path / "c1")
        decided = _run("decide", db, port, tmp_path / "c1")
        again = _run("suggest", db, port, tmp_path / "c2")

    assert first == {
        "Globex": "pending",
        "Initech": "pending",
        "https://evil.example": "invalid",
    }
    assert decided == {"approved": "Globex", "watchlist": ["Globex"]}
    assert again == {
        "Globex": "already_watched",
        "Initech": "denied",
        "https://evil.example": "invalid",
    }
    with closing(connect(db)) as conn:
        states = dict(conn.execute("SELECT name, state FROM suggestion").fetchall())
    assert states == {"Globex": "approved", "Initech": "denied"}
