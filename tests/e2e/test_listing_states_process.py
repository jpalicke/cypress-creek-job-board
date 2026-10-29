# ABOUTME: Runs listing refreshes in separate child processes sharing one SQLite file.
# ABOUTME: A shrunk board closes a listing, and a failed fetch exits loudly and closes nothing.
import json
import subprocess
import sys
from pathlib import Path

from http_support import http_server

TESTS_DIR = Path(__file__).parent.parent
FIXTURE = TESTS_DIR / "fixtures" / "lever" / "palantir_page.json"
POSTINGS = json.loads(FIXTURE.read_text(encoding="utf-8"))
SLUG = "examplecoboard"
PATH = f"/us/{SLUG}?mode=json&limit=100&skip=0"

# The child refreshes the board with a real Lever adapter over the test-only loopback resolver,
# applies it to the database file, and prints the states of every stored listing of the board.
CHILD = r"""
import json
import sys
from pathlib import Path

database, tests_dir, port, cache = sys.argv[1:5]
sys.path.insert(0, tests_dir)

from cypress_creek.discovery.adapters.lever import LEVER_FETCH_LIMITS, LeverAdapter
from cypress_creek.discovery.cache import ResponseCache
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.listings import Listings
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.ingest.safe_http import _fetch
from cypress_creek.storage.db import connect, migrate
from http_support import local_target


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
conn = connect(Path(database))
migrate(conn)
listings = Listings(conn)
changes = listings.refresh(adapter, "lever", sys.argv[5])
states = {item.id: item.state.value for item in listings.board("lever", sys.argv[5])}
print(json.dumps({"changes": [changes.added, changes.seen, changes.closed], "states": states}))
conn.close()
"""


def _refresh(
    database: Path, port: int, cache: Path, slug: str = SLUG
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", CHILD, str(database), str(TESTS_DIR), str(port), str(cache), slug],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _ok(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


def _ids(postings: list[dict[str, object]]) -> set[str]:
    return {f"lever:{SLUG}:{posting['id']}" for posting in postings}


def test_a_board_that_shrinks_between_processes_closes_the_missing_listing(tmp_path: Path) -> None:
    database = tmp_path / "app.sqlite3"
    full = json.dumps(POSTINGS).encode("utf-8")
    shrunk = json.dumps(POSTINGS[:2]).encode("utf-8")

    with http_server({PATH: full}) as (port, _):
        first = _ok(_refresh(database, port, tmp_path / "cache-1"))
    assert first["changes"] == [3, 0, 0]
    assert set(first["states"]) == _ids(POSTINGS)  # type: ignore[call-overload]
    assert set(first["states"].values()) == {"new"}  # type: ignore[attr-defined]

    with http_server({PATH: shrunk}) as (port, _):
        second = _ok(_refresh(database, port, tmp_path / "cache-2"))
    assert second["changes"] == [0, 2, 1]
    states = second["states"]
    assert isinstance(states, dict)
    assert states[f"lever:{SLUG}:{POSTINGS[0]['id']}"] == "seen"
    assert states[f"lever:{SLUG}:{POSTINGS[2]['id']}"] == "closed"


def test_a_failed_fetch_in_a_later_process_exits_loudly_and_closes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "app.sqlite3"
    full = json.dumps(POSTINGS).encode("utf-8")

    with http_server({PATH: full}) as (port, _):
        _ok(_refresh(database, port, tmp_path / "cache-1"))

    with http_server({}) as (port, requests):
        failed = _refresh(database, port, tmp_path / "cache-2")
        assert len(requests.received) == 2
    assert failed.returncode != 0
    assert "BoardNotFound" in failed.stderr

    with http_server({PATH: full}) as (port, _):
        again = _ok(_refresh(database, port, tmp_path / "cache-3"))
    assert again["changes"] == [0, 3, 0]
    assert set(again["states"].values()) == {"seen"}  # type: ignore[attr-defined]
