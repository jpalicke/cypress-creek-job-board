# ABOUTME: Refreshes real public Lever boards through the real server app and the real adapters.
# ABOUTME: A stored EU region reaches the EU host first. The cap is 0, so no model is called.
from datetime import UTC, datetime
from pathlib import Path

import pytest
from api_support import ApiClient, post_json

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings
from cypress_creek.discovery.adapters.lever import LeverRegion
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.storage.db import connect
from cypress_creek.storage.repository import prepare_database

pytestmark = pytest.mark.needs_network

ROOT = Path(__file__).parent.parent.parent
BANK = ROOT / "evals" / "bank" / "sample_bank.yaml"
APPROVED = datetime(2026, 1, 1, tzinfo=UTC)
# A board that lives only on the EU host (see test_lever_network.py), and a slug no board has.
EU_ONLY_BOARD = "kaiko"
MISSING_BOARD = "zz-no-such-board-9f3c1b7a2e4d58061a7c3e9b5d2f4a68"


def test_real_boards_are_fetched_through_the_default_adapters_with_a_stored_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CYPRESS_CREEK_DATA_DIR", str(tmp_path / "data"))
    database = tmp_path / "app.sqlite3"
    prepare_database(database)
    conn = connect(database)
    watchlist = Watchlist(conn)
    watchlist.add(
        WatchlistEntry(
            "Eu Board", "lever", EU_ONLY_BOARD, IdentityEvidence.WEAK, APPROVED, LeverRegion.EU
        )
    )
    watchlist.add(
        WatchlistEntry("Missing Co", "lever", MISSING_BOARD, IdentityEvidence.NONE, APPROVED)
    )
    conn.close()
    app = create_app(
        ProviderSettings(provider="ollama", model="qwen3.5:0.8b"),
        static_dir=None,
        database_path=database,
        bank_path=BANK,
    )
    client = ApiClient(app)

    response = post_json(client, "/api/discovery/refresh", {"backend": "ollama", "cap": 0})

    assert response.status_code == 200, response.text
    summary = response.json()
    assert [(e["slug"], e["reason"]) for e in summary["errors"]] == [
        (MISSING_BOARD, "BoardNotFound")
    ]
    assert summary["stopped_by"] in ("cap", None)
    assert (tmp_path / "data" / "fetch_cache").is_dir()
