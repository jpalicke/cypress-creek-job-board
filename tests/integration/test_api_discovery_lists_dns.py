# ABOUTME: Proves the watchlist and blacklist routes never resolve a name while DNS is available.
# ABOUTME: A recording passthrough wraps the real getaddrinfo, and the test itself resolves a host.
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from api_support import ApiClient, post_json

from cypress_creek.api.app import create_app

pytestmark = pytest.mark.needs_network

ADD = {
    "display_name": "Example Co",
    "ats": "greenhouse",
    "slug": "exampleco",
    "identity_evidence": "weak",
    "approval": "human_confirmed",
}


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every getaddrinfo host and then calls the real resolver."""
    seen: list[str] = []
    real: Callable[..., Any] = socket.getaddrinfo

    def recording(host: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(str(host))
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", recording)
    return seen


def test_the_recorder_sees_a_real_lookup_so_the_assertion_is_not_vacuous(
    lookups: list[str],
) -> None:
    assert socket.getaddrinfo("example.com", 443)
    assert lookups == ["example.com"]


def test_the_list_routes_make_no_dns_lookup_for_the_names_they_hold(
    tmp_path: Path, lookups: list[str]
) -> None:
    client = ApiClient(create_app(None, static_dir=None, database_path=tmp_path / "app.sqlite3"))

    domain = post_json(
        client,
        "/api/blacklist",
        {"match_kind": "domain", "value": "https://www.example.com/jobs", "reason": "agency"},
    )
    refused = post_json(
        client,
        "/api/blacklist",
        {"match_kind": "company_key", "value": "Example Co", "reason": "x"},
    )
    blocked = post_json(client, "/api/watchlist", ADD)
    listed = [client.get("/api/blacklist"), client.get("/api/watchlist")]

    assert domain.status_code == 201
    assert domain.json()["value"] == "example.com"
    assert refused.status_code == 201
    assert blocked.status_code == 409
    assert [answer.status_code for answer in listed] == [200, 200]
    assert lookups == []
    # The blocked domain is a real, resolvable host: the routes stored it without resolving it.
    assert socket.getaddrinfo("example.com", 443)
    assert lookups == ["example.com"]
