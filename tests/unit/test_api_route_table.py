# ABOUTME: Enumerates the route table and fails if any route could submit, send or post outward.
# ABOUTME: The product never applies, mails or posts anywhere, so no route name may suggest it.
import re
from typing import Any

from fastapi import FastAPI

from cypress_creek.api.app import create_app
from cypress_creek.api.security import allowed_hosts

OUTWARD = re.compile(
    r"submit|send|apply|mail|publish|external|webhook|tweet|post[-_]?to|auto[-_]?",
    re.IGNORECASE,
)


def operations(app: FastAPI) -> dict[str, dict[str, Any]]:
    """Every path and its operations, from the app's own schema, not from private route classes."""
    paths: dict[str, dict[str, Any]] = app.openapi()["paths"]
    return paths


def outward_routes(app: FastAPI) -> list[str]:
    found = []
    for path, methods in operations(app).items():
        names = [str(op.get("operationId", "")) for op in methods.values()]
        if OUTWARD.search(path) or any(OUTWARD.search(name) for name in names):
            found.append(path)
    return sorted(found)


def test_no_route_suggests_submitting_sending_applying_or_posting_outward() -> None:
    assert outward_routes(create_app(None)) == []


def test_the_check_would_catch_an_offending_route() -> None:
    app = create_app(None)

    @app.post("/api/postings/{posting_id}/apply")
    def apply_now(posting_id: str) -> None: ...

    @app.get("/api/okay")
    def send_mail() -> None: ...

    assert outward_routes(app) == ["/api/okay", "/api/postings/{posting_id}/apply"]


def test_the_route_table_holds_only_the_known_routes() -> None:
    assert set(operations(create_app(None))) == {
        "/api/health",
        "/api/providers",
        "/api/session",
        "/api/postings",
        "/api/postings/{posting_id}/estimate",
        "/api/postings/{posting_id}/analyze",
        "/api/reports/{report_id}",
        "/api/facts",
        "/api/facts/validate",
        "/api/watchlist",
        "/api/blacklist",
        "/api/blacklist/{entry_id}",
        "/api/discovery/refresh",
        "/api/discovery/listings",
    }


def test_allowed_hosts_are_the_two_loopback_names_on_the_port() -> None:
    assert allowed_hosts(5309) == frozenset({"127.0.0.1:5309", "localhost:5309"})
