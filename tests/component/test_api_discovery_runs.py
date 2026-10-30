# ABOUTME: Drives the discovery refresh and listing routes of the real app over a real database.
# ABOUTME: Boards are loopback servers behind the real Lever adapter; the model is unreachable.
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_support import ApiClient, csrf_headers, post_json
from discovery_support import (
    BACKEND,
    BANK,
    MODEL,
    NOW,
    SLUG,
    TODAY,
    Scorer,
    lever_adapter,
    lever_routes,
)
from http_support import Requests, http_server

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings
from cypress_creek.discovery.adapters.lever import LeverAdapter
from cypress_creek.discovery.blacklist import BlacklistEntry, BlockReason
from cypress_creek.discovery.blacklist_repository import Blacklist
from cypress_creek.discovery.filters import ListingFilters
from cypress_creek.discovery.run import RunIdentity, run_discovery
from cypress_creek.discovery.watchlist import IdentityEvidence, Watchlist, WatchlistEntry
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.storage.db import connect
from cypress_creek.storage.repository import prepare_database


@pytest.fixture
def bank_file(tmp_path: Path) -> Path:
    path = tmp_path / "bank.yaml"
    path.write_text(BANK, encoding="utf8")
    return path


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "app.sqlite3"
    prepare_database(path)
    connection = connect(path)
    Watchlist(connection).add(
        WatchlistEntry("Example Co", "lever", SLUG, IdentityEvidence.WEAK, NOW)
    )
    connection.close()
    return path


def make_client(
    tmp_path: Path, database: Path, bank_file: Path, adapter: LeverAdapter
) -> ApiClient:
    settings = ProviderSettings.model_validate(
        {"provider": BACKEND, "model": MODEL, "base_url": "http://127.0.0.1:1"}
    )
    app = create_app(
        settings,
        static_dir=None,
        database_path=database,
        bank_path=bank_file,
        adapters={"lever": adapter},
    )
    return ApiClient(app)


@pytest.fixture
def serving() -> Iterator[tuple[int, Requests]]:
    with http_server(lever_routes(6)) as (port, requests):
        yield port, requests


def refresh(client: ApiClient, **body: object) -> dict[str, Any]:
    response = post_json(client, "/api/discovery/refresh", {"backend": BACKEND, **body})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def prescore(database: Path, bank_file: Path, adapter: LeverAdapter, cap: int = 30) -> None:
    """Score the board through the library with recorded requirements, as a first run would."""
    bank = load_bank(bank_file)
    connection = connect(database)
    try:
        run_discovery(
            connection,
            {"lever": adapter},
            [],
            ListingFilters(),
            Scorer(bank),
            RunIdentity(bank_digest=bank_hash(bank), backend=BACKEND, model=MODEL),
            cap=cap,
            today=TODAY,
            now=NOW,
        )
    finally:
        connection.close()


def test_a_refresh_with_the_backend_down_fetches_and_stops_with_nothing_scored(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, _ = serving
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))

    summary = refresh(client)

    assert summary["fetched"] == 6
    assert summary["scored"] == 0
    assert summary["stopped_by"] == "backend"
    assert summary["unscored"] == 6
    assert summary["errors"] == []
    listed = client.get("/api/discovery/listings").json()
    assert {row["status"] for row in listed["listings"]} == {"unscored"}
    assert len(listed["listings"]) == 6


def test_a_refresh_after_a_scoring_run_is_served_from_the_score_cache(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, _ = serving
    prescore(database, bank_file, lever_adapter(tmp_path / "first", port))
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path / "second", port))

    summary = refresh(client)

    assert summary["scored"] == 0
    assert summary["cache_hits"] == 6
    assert summary["stopped_by"] is None
    assert summary["unscored"] == 0


def test_the_ranked_list_carries_score_counts_source_age_and_the_report_link(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, _ = serving
    prescore(database, bank_file, lever_adapter(tmp_path / "first", port))
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path / "second", port))

    body = client.get("/api/discovery/listings").json()

    assert "triage" in body["note"]
    assert "not a probability" in body["note"]
    rows = body["listings"]
    assert len(rows) == 6
    first = rows[0]
    assert set(first) == {
        "id",
        "title",
        "location",
        "ats",
        "slug",
        "urls",
        "posted_at",
        "age_days",
        "status",
        "score",
        "strong",
        "partial",
        "none",
        "incomplete",
        "run_id",
    }
    assert first["ats"] == "lever"
    assert first["slug"] == SLUG
    assert first["status"] == "scored"
    assert first["run_id"] is not None
    assert first["run_id"].startswith("run-")
    assert first["urls"][0].startswith("https://")
    assert isinstance(first["age_days"], int)
    assert "content_text" not in first


def test_the_listings_are_ranked_by_score_then_recency(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, _ = serving
    prescore(database, bank_file, lever_adapter(tmp_path / "first", port))
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path / "second", port))

    rows = client.get("/api/discovery/listings").json()["listings"]

    scores = [row["score"] for row in rows]
    assert scores == sorted(scores, key=lambda s: -(s if s is not None else -1.0))
    ids = [row["id"] for row in rows]
    assert ids == [f"lever:{SLUG}:posting-{n}" for n in (5, 4, 3, 2, 1, 0)]


def test_a_blacklisted_company_is_never_fetched(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, requests = serving
    connection = connect(database)
    Blacklist(connection).add(
        BlacklistEntry(BlockReason.COMPANY_KEY, "Example Co", "not a fit", NOW)
    )
    connection.close()
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))

    summary = refresh(client)

    assert summary["blocked_boards"] == 1
    assert summary["fetched"] == 0
    assert requests.received == []
    assert client.get("/api/discovery/listings").json()["listings"] == []


def test_the_request_filters_remove_listings_and_are_counted(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, _ = serving
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))

    summary = refresh(client, filters={"include_keywords": ["no such phrase anywhere"]})

    assert summary["unscored"] == 0
    assert sum(summary["filtered_out"].values()) == 6
    assert summary["stopped_by"] is None


def test_the_cap_limits_the_model_calls_of_a_refresh(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, _ = serving
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))

    summary = refresh(client, cap=0)

    assert summary["stopped_by"] == "cap"
    assert summary["unscored"] == 6


def test_a_failing_board_is_reported_and_the_run_still_answers(
    tmp_path: Path, database: Path, bank_file: Path
) -> None:
    with http_server({}) as (port, _):
        client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))
        summary = refresh(client)

    assert summary["fetched"] == 0
    errors = summary["errors"]
    assert [(e["ats"], e["slug"]) for e in errors] == [("lever", SLUG)]
    assert "http" not in errors[0]["reason"]


def test_an_empty_watchlist_refreshes_to_nothing(
    tmp_path: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, requests = serving
    empty = tmp_path / "empty.sqlite3"
    prepare_database(empty)
    client = make_client(tmp_path, empty, bank_file, lever_adapter(tmp_path, port))

    summary = refresh(client)

    assert summary["fetched"] == 0
    assert requests.received == []
    assert client.get("/api/discovery/listings").json()["listings"] == []


def test_refresh_needs_the_csrf_token(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, requests = serving
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))

    response = client.post("/api/discovery/refresh", json={"backend": BACKEND})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_token_invalid"
    assert requests.received == []


@pytest.mark.parametrize(
    "body",
    [
        {"backend": BACKEND, "surprise": True},
        {"backend": BACKEND, "cap": -1},
        {"backend": BACKEND, "filters": {"include_keywords": [" "]}},
        {"backend": BACKEND, "filters": {"apply": True}},
        {},
    ],
)
def test_a_bad_refresh_body_is_a_typed_422_and_fetches_nothing(
    tmp_path: Path,
    database: Path,
    bank_file: Path,
    serving: tuple[int, Requests],
    body: dict[str, object],
) -> None:
    port, requests = serving
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))

    response = post_json(client, "/api/discovery/refresh", body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert requests.received == []


def test_a_backend_that_is_not_the_configured_one_is_refused_before_any_fetch(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, requests = serving
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))

    response = post_json(client, "/api/discovery/refresh", {"backend": "anthropic"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_backend"
    assert requests.received == []


def test_a_refresh_without_a_configured_backend_is_refused(
    tmp_path: Path, database: Path, bank_file: Path
) -> None:
    app = create_app(
        None, static_dir=None, database_path=database, bank_path=bank_file, adapters={}
    )
    client = ApiClient(app)

    response = post_json(client, "/api/discovery/refresh", {"backend": BACKEND})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_backend"


def test_a_missing_bank_is_a_typed_error(
    tmp_path: Path, database: Path, serving: tuple[int, Requests]
) -> None:
    port, requests = serving
    client = make_client(
        tmp_path, database, tmp_path / "missing.yaml", lever_adapter(tmp_path, port)
    )

    response = post_json(client, "/api/discovery/refresh", {"backend": BACKEND})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "bank_not_found"
    assert requests.received == []


def test_listing_filters_come_from_the_query(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, _ = serving
    prescore(database, bank_file, lever_adapter(tmp_path / "first", port))
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path / "second", port))

    none = client.get("/api/discovery/listings", params={"include_keyword": "no such phrase"})
    some = client.get("/api/discovery/listings", params={"max_age_days": 100000})
    bad = client.get("/api/discovery/listings", params={"max_age_days": 0})

    assert none.json()["listings"] == []
    assert len(some.json()["listings"]) == 6
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid_request"


def test_no_discovery_route_changes_state_outside_the_database(
    tmp_path: Path, database: Path, bank_file: Path, serving: tuple[int, Requests]
) -> None:
    port, requests = serving
    client = make_client(tmp_path, database, bank_file, lever_adapter(tmp_path, port))
    refresh(client)

    assert set(requests.methods) == {"GET"}
    assert client.get("/api/session").status_code == 200
    headers = csrf_headers(client)
    assert client.request("DELETE", "/api/discovery/listings", headers=headers).status_code in (
        404,
        405,
    )
