# ABOUTME: Builds a fact bank through the real API server process and reads the file it wrote.
# ABOUTME: Verification only comes from the verify call, and a second process sees the same bank.
import http.client
import json
from pathlib import Path

from api_server_support import PORT, call, running_server

from cypress_creek.facts.loader import load_bank

FACT = {
    "claim": "Built a reporting service in Python.",
    "kind": "project",
    "tags": [{"name": "python", "level": "working"}],
    "evidence": {"type": "self_attested", "pointer": "my notes"},
}


def delete(path: str, token: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    try:
        connection.request("DELETE", path, headers={"X-CSRF-Token": token})
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def test_a_bank_is_built_verified_and_kept_across_server_restarts(tmp_path: Path) -> None:
    bank = tmp_path / "private" / "bank.yaml"
    with running_server(tmp_path, bank):
        _, session = call("GET", "/api/session")
        token = session["csrf_token"]  # type: ignore[index]
        assert call("GET", "/api/facts")[0] == 404

        status, created = call("POST", "/api/facts", FACT, token)
        assert status == 201 and created["id"] == "F-0001"  # type: ignore[index]
        assert created.get("verified_on") is None  # type: ignore[attr-defined]
        assert load_bank(bank).unverified_ids() == ["F-0001"]

        assert call("POST", "/api/facts", FACT)[0] == 403
        status, verified = call("POST", "/api/facts/F-0001/verify", None, token)
        assert status == 200 and verified["verified_on"]  # type: ignore[index]

        status, edited = call("PUT", "/api/facts/F-0001", {**FACT, "claim": "Changed."}, token)
        assert status == 200 and edited.get("verified_on") is None  # type: ignore[attr-defined]

    with running_server(tmp_path, bank):
        _, session = call("GET", "/api/session")
        _, listed = call("GET", "/api/facts")
        assert [f["claim"] for f in listed["facts"]] == ["Changed."]  # type: ignore[index]
        assert delete("/api/facts/F-0001", session["csrf_token"]) == 200  # type: ignore[index]
        assert call("GET", "/api/facts")[1]["facts"] == []  # type: ignore[index]

    assert json.loads(json.dumps(load_bank(bank).model_dump(mode="json")))["facts"] == []
