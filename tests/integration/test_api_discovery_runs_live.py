# ABOUTME: Live check of the discovery routes: recorded postings behind a real adapter, real Ollama.
# ABOUTME: An unreachable server or missing model fails loudly. The score cache is read back.
import json
import os
from pathlib import Path

import httpx
import pytest
from api_support import ApiClient, post_json
from discovery_support import FIXTURE, NOW, SLUG, lever_adapter
from http_support import http_server

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.storage.db import connect
from cypress_creek.storage.repository import prepare_database

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
ROOT = Path(__file__).parent.parent.parent
BANK = ROOT / "evals" / "bank" / "sample_bank.yaml"
CAP = 2


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


def test_a_refresh_scores_under_the_cap_with_a_real_model_and_the_list_shows_the_scores(
    tmp_path: Path,
) -> None:
    database = tmp_path / "app.sqlite3"
    prepare_database(database)
    conn = connect(database)
    Watchlist(conn).add(WatchlistEntry("Example Co", "lever", SLUG, IdentityEvidence.WEAK, NOW))
    conn.close()
    total = len(json.loads(FIXTURE.read_text(encoding="utf-8")))
    routes = {f"/us/{SLUG}?mode=json&limit=100&skip=0": FIXTURE.read_bytes()}
    settings = ProviderSettings(
        provider="ollama", model=MODEL, base_url=BASE_URL, context_tokens=8192
    )
    with http_server(routes) as (port, _):
        app = create_app(
            settings,
            static_dir=None,
            database_path=database,
            bank_path=BANK,
            adapters={"lever": lever_adapter(tmp_path, port)},
        )
        client = ApiClient(app)

        response = post_json(client, "/api/discovery/refresh", {"backend": "ollama", "cap": CAP})

    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["fetched"] == total
    assert summary["scored"] + summary["cache_hits"] <= CAP
    assert summary["stopped_by"] in ("cap", "backend", None)
    listed = client.get("/api/discovery/listings").json()
    assert len(listed["listings"]) == total
    scored = [row for row in listed["listings"] if row["status"] != "unscored"]
    assert len(scored) == summary["scored"]
    assert all(row["run_id"].startswith("run-") for row in scored)
