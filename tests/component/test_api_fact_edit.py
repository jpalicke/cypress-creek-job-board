# ABOUTME: Drives the fact bank edit routes of the real app on a real bank file in a temp folder.
# ABOUTME: Verification only comes from its own route, and editing what a fact says undoes it.
from pathlib import Path

import pytest
from api_support import ApiClient, csrf_headers, post_json

from cypress_creek.api.app import create_app
from cypress_creek.facts.loader import load_bank

NEW = {
    "claim": "Built a reporting service in Python.",
    "kind": "project",
    "tags": [{"name": "python", "level": "working"}],
    "evidence": {"type": "self_attested", "pointer": "my notes"},
}


def send(client: ApiClient, method: str, url: str, body: object = None) -> object:
    headers = csrf_headers(client, {"content-type": "application/json"})
    kwargs = {"json": body} if body is not None else {}
    return client.request(method, url, headers=headers, **kwargs)


@pytest.fixture
def client(tmp_path: Path) -> ApiClient:
    app = create_app(
        None,
        static_dir=None,
        database_path=tmp_path / "db.sqlite3",
        bank_path=tmp_path / "private" / "bank.yaml",
    )
    return ApiClient(app)


def add(client: ApiClient, **changes: object) -> dict[str, object]:
    response = post_json(client, "/api/facts", {**NEW, **changes})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_a_new_fact_is_unverified_and_local_only_and_listed(client: ApiClient) -> None:
    fact = add(client)

    assert fact["id"] == "F-0001"
    assert "verified_on" not in fact or fact["verified_on"] is None
    assert fact["share"] == "local_only"
    listed = client.get("/api/facts").json()
    assert [f["id"] for f in listed["facts"]] == ["F-0001"]
    assert listed["unverified_ids"] == ["F-0001"]


def test_an_add_cannot_set_verification_share_or_an_id(client: ApiClient) -> None:
    for extra in ({"verified_on": "2026-01-01"}, {"share": "shareable"}, {"id": "F-0009"}):
        response = post_json(client, "/api/facts", {**NEW, **extra})
        assert response.status_code == 422
    assert client.get("/api/facts").status_code == 404


def test_verify_is_its_own_route_and_touches_only_that_fact(client: ApiClient) -> None:
    add(client)
    add(client, claim="Another claim.")

    response = send(client, "POST", "/api/facts/F-0001/verify")

    assert response.status_code == 200  # type: ignore[attr-defined]
    facts = {f["id"]: f for f in client.get("/api/facts").json()["facts"]}
    assert facts["F-0001"]["verified_on"] is not None
    assert facts["F-0002"].get("verified_on") is None


def test_editing_the_claim_of_a_verified_fact_unverifies_it(client: ApiClient) -> None:
    add(client)
    send(client, "POST", "/api/facts/F-0001/verify")

    response = send(client, "PUT", "/api/facts/F-0001", {**NEW, "claim": "A different claim."})

    assert response.status_code == 200  # type: ignore[attr-defined]
    assert response.json().get("verified_on") is None  # type: ignore[attr-defined]
    assert client.get("/api/facts").json()["unverified_ids"] == ["F-0001"]


def test_share_is_a_separate_route_and_keeps_verification(client: ApiClient) -> None:
    add(client)
    send(client, "POST", "/api/facts/F-0001/verify")

    response = send(client, "PUT", "/api/facts/F-0001/share", {"share": "shareable"})

    body = response.json()  # type: ignore[attr-defined]
    assert body["share"] == "shareable" and body["verified_on"] is not None


def test_unverify_and_delete(client: ApiClient) -> None:
    add(client)
    send(client, "POST", "/api/facts/F-0001/verify")

    unverified = send(client, "POST", "/api/facts/F-0001/unverify")
    removed = send(client, "DELETE", "/api/facts/F-0001")

    assert unverified.json().get("verified_on") is None  # type: ignore[attr-defined]
    assert removed.status_code == 200  # type: ignore[attr-defined]
    assert client.get("/api/facts").json()["facts"] == []


def test_an_invalid_fact_gets_a_typed_error_next_to_the_field_and_saves_nothing(
    client: ApiClient,
) -> None:
    response = post_json(client, "/api/facts", {**NEW, "start": "2999-01-01"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"][0]["field"] == "start"
    assert client.get("/api/facts").status_code == 404


def test_a_bad_tag_level_is_a_typed_error_on_that_field(client: ApiClient) -> None:
    bad = {**NEW, "tags": [{"name": "python", "level": "wizard"}]}

    response = post_json(client, "/api/facts", bad)

    assert response.status_code == 422
    assert any("tags" in d["field"] for d in response.json()["error"]["details"])


def test_an_unknown_fact_is_a_typed_404_and_a_bad_id_cannot_reach_the_file(
    client: ApiClient,
) -> None:
    add(client)

    for method, url in (
        ("PUT", "/api/facts/F-0099"),
        ("POST", "/api/facts/F-0099/verify"),
        ("DELETE", "/api/facts/F-0099"),
        ("DELETE", "/api/facts/..%2Fbank"),
        ("DELETE", "/api/facts/F-1"),
    ):
        response = send(client, method, url, NEW if method == "PUT" else None)
        assert response.status_code in (404, 422), url  # type: ignore[attr-defined]
    assert len(client.get("/api/facts").json()["facts"]) == 1


def test_every_write_needs_the_csrf_token(client: ApiClient) -> None:
    add(client)

    for method, url in (
        ("POST", "/api/facts"),
        ("PUT", "/api/facts/F-0001"),
        ("POST", "/api/facts/F-0001/verify"),
        ("PUT", "/api/facts/F-0001/share"),
        ("DELETE", "/api/facts/F-0001"),
    ):
        refused = client.request(method, url, json=NEW)
        assert refused.status_code == 403, url
    assert client.get("/api/facts").json()["unverified_ids"] == ["F-0001"]


def test_hostile_text_is_stored_and_returned_as_plain_text(
    client: ApiClient, tmp_path: Path
) -> None:
    hostile = '<script>alert(1)</script><img src=x onerror="alert(2)">'

    fact = add(client, claim=hostile)

    assert fact["claim"] == hostile
    assert load_bank(tmp_path / "private" / "bank.yaml").facts[0].claim == hostile
    assert "<script>" not in client.get("/api/facts").headers.get("content-type", "")


def test_an_oversized_claim_is_refused_by_the_fact_rules(client: ApiClient) -> None:
    response = post_json(client, "/api/facts", {**NEW, "claim": "x" * 301})

    assert response.status_code == 422
