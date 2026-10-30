# ABOUTME: Drives the fact bank routes of the real app against the real fictional sample bank.
# ABOUTME: The validate route must report problems as data and never echo the submitted YAML.
from pathlib import Path

import pytest
from api_support import ApiClient, post_json

from cypress_creek.api.app import create_app

ROOT = Path(__file__).parent.parent.parent
BANK = ROOT / "evals" / "bank" / "sample_bank.yaml"
BANK_TEXT = BANK.read_text(encoding="utf-8")


def make_client(tmp_path: Path, bank: Path | None = BANK) -> ApiClient:
    return ApiClient(
        create_app(None, static_dir=None, database_path=tmp_path / "db.sqlite3", bank_path=bank)
    )


def test_the_bank_is_listed_with_its_unverified_ids(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/api/facts")

    assert response.status_code == 200
    body = response.json()
    assert len(body["facts"]) == 25
    first = body["facts"][0]
    assert first["id"] == "F-0001"
    assert first["share"] == "shareable"
    assert body["unverified_ids"] == []


def test_a_missing_bank_is_a_typed_404_that_does_not_name_the_path(tmp_path: Path) -> None:
    client = make_client(tmp_path, tmp_path / "secret-location" / "bank.yaml")

    response = client.get("/api/facts")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "bank_not_found"
    assert "secret-location" not in response.text


def test_a_good_bank_file_validates(tmp_path: Path) -> None:
    response = post_json(make_client(tmp_path), "/api/facts/validate", {"yaml": BANK_TEXT})

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "fact_count": 25,
        "unverified_ids": [],
        "problem": None,
    }


def test_strict_validation_refuses_an_unverified_fact(tmp_path: Path) -> None:
    unverified = (ROOT / "evals" / "bank" / "sample_bank_unverified.yaml").read_text(
        encoding="utf-8"
    )
    client = make_client(tmp_path)

    lax = post_json(client, "/api/facts/validate", {"yaml": unverified}).json()
    strict = post_json(client, "/api/facts/validate", {"yaml": unverified, "strict": True}).json()

    assert lax["valid"] is True
    assert lax["unverified_ids"] == ["F-0026"]
    assert strict["valid"] is False
    assert strict["problem"] == {
        "fact_id": "F-0026",
        "field": "verified_on",
        "reason": "required in strict mode",
    }


@pytest.mark.parametrize(
    "text",
    [
        "facts: [",
        "not: a bank",
        "facts:\n  - &a {id: F-1}\n  - *a",
        "facts:\n  - id: F-1\n    claim: x\n    kind: nonsense\n",
    ],
)
def test_a_broken_bank_is_reported_as_data_and_not_echoed(tmp_path: Path, text: str) -> None:
    response = post_json(make_client(tmp_path), "/api/facts/validate", {"yaml": text})

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["fact_count"] == 0
    assert body["problem"]["reason"]
    assert "Traceback" not in response.text
