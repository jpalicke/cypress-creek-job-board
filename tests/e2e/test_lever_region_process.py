# ABOUTME: Proves a Lever region stored by one process is used by a fresh process to ask one host.
# ABOUTME: Real child processes share a SQLite file and fetch from a real loopback server.
import json
import subprocess
import sys
from pathlib import Path

from http_support import http_server

FIXTURES = Path(__file__).parent.parent / "fixtures" / "lever" / "palantir_page.json"
RECORDED_COUNT = len(json.loads(FIXTURES.read_text(encoding="utf-8")))
TESTS_DIR = Path(__file__).parent.parent
SLUG = "examplecoboard"
EU_PATH = f"/eu/{SLUG}?mode=json&limit=100&skip=0"
US_PATH = f"/us/{SLUG}?mode=json&limit=100&skip=0"

# The child opens the database file. Mode "write" adds a Lever entry and stores its region.
# Modes "seeded" and "unseeded" read the entries and fetch each board with a real adapter and
# the explicitly test-only loopback resolver, seeding the stored region only in "seeded".
CHILD = r"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

database, mode, tests_dir, port, cache = sys.argv[1:6]
sys.path.insert(0, tests_dir)

from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter, LeverRegion
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.ingest.safe_http import _fetch
from cypress_creek.storage.db import connect, migrate
from http_support import local_target

conn = connect(Path(database))
migrate(conn)
watchlist = Watchlist(conn)
if mode == "write":
    watchlist.add(
        WatchlistEntry(
            "Example Co", "lever", "ExampleCoBoard", IdentityEvidence.WEAK, datetime.now(UTC)
        )
    )
    print(json.dumps({"stored": watchlist.set_region("lever", "examplecoboard", LeverRegion.EU)}))
else:

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
    (entry,) = watchlist.entries()
    if mode == "seeded" and entry.region is not None:
        adapter.remember_region(entry.slug, entry.region)
    fetched = adapter.fetch_board(entry.slug)
    region = adapter.region_of(entry.slug)
    print(
        json.dumps(
            {
                "stored_region": entry.region.value if entry.region else None,
                "listings": len(fetched.listings),
                "region": region.value if region else None,
            }
        )
    )
conn.close()
"""


def _run(database: Path, mode: str, port: int, cache: Path) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(database), mode, str(TESTS_DIR), str(port), str(cache)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


def _routes() -> dict[str, bytes]:
    return {EU_PATH: FIXTURES.read_bytes()}


def test_a_fresh_process_asks_only_the_stored_host(tmp_path: Path) -> None:
    database = tmp_path / "app.sqlite3"
    with http_server(_routes()) as (port, requests):
        assert _run(database, "write", port, tmp_path / "unused") == {"stored": True}
        assert requests.received == []

        outcome = _run(database, "seeded", port, tmp_path / "cache-seeded")

        assert [path for path, _ in requests.received] == [EU_PATH]
    assert outcome == {"stored_region": "eu", "listings": RECORDED_COUNT, "region": "eu"}


def test_without_the_seed_the_same_process_asks_the_us_host_first(tmp_path: Path) -> None:
    database = tmp_path / "app.sqlite3"
    with http_server(_routes()) as (port, requests):
        _run(database, "write", port, tmp_path / "unused")

        outcome = _run(database, "unseeded", port, tmp_path / "cache-unseeded")

        assert [path for path, _ in requests.received] == [US_PATH, EU_PATH]
    assert outcome["region"] == "eu"
