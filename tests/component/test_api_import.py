# ABOUTME: Drives the resume import routes of the real app with hand written model replies.
# ABOUTME: A hostile reply never becomes a pending fact, and approving never verifies anything.
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

import pytest
from api_support import ApiClient, csrf_headers, post_json
from chat_server import Reply, chat_server, json_reply

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings
from cypress_creek.facts.loader import load_bank
from cypress_creek.pipeline.prompt import Stage, build_prompt
from cypress_creek.pipeline.schemas import ResumeImportOutput
from cypress_creek.providers.base import Capabilities, CostPerMtok
from cypress_creek.storage.repository import prepare_database

FIXTURES = Path(__file__).parent.parent / "fixtures" / "resume"
RESUME = (FIXTURES / "fictional_resume.txt").read_text(encoding="utf-8")
HOSTILE = (FIXTURES / "hostile_resume.txt").read_text(encoding="utf-8")
PDFS = Path(__file__).parent.parent.parent / "evals" / "fixtures" / "pdf"
GOOD = {
    "claim": "Built Python services.",
    "kind": "employment",
    "tags": ["Python"],
    "source": "Built Python services and cut the nightly batch from 6 hours to 90 minutes",
}


def reply(*candidates: Mapping[str, object]) -> Reply:
    output = {"schema_version": 1, "candidates": list(candidates)}
    return json_reply(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(output)},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
    )


def make(tmp_path: Path, base_url: str, **settings: object) -> ApiClient:
    fields: dict[str, object] = {
        "provider": "openai_compatible",
        "model": "local-model",
        "base_url": base_url,
        "context_tokens": 8192,
    }
    fields.update(settings)
    prepare_database(tmp_path / "app.sqlite3")
    app = create_app(
        ProviderSettings.model_validate(fields),
        static_dir=None,
        database_path=tmp_path / "app.sqlite3",
        bank_path=tmp_path / "private" / "bank.yaml",
    )
    return ApiClient(app)


def run(client: ApiClient, text: str = RESUME, **extra: object):  # type: ignore[no-untyped-def]
    body = {"text": text, "backend": "openai_compatible", **extra}
    return post_json(client, "/api/import/resume", body)


def send(client: ApiClient, method: str, url: str):  # type: ignore[no-untyped-def]
    return client.request(
        method, url, headers=csrf_headers(client, {"content-type": "application/json"})
    )


def test_a_grounded_candidate_becomes_pending_and_the_resume_is_not_stored(
    tmp_path: Path,
) -> None:
    with chat_server(reply(GOOD)) as (base_url, log):
        client = make(tmp_path, base_url)
        response = run(client)

    body = response.json()
    assert response.status_code == 200 and body["status"] == "done"
    (candidate,) = body["candidates"]
    assert candidate["state"] == "pending" and candidate["tags"] == ["python"]
    assert body["dropped"] == {} and body["hosted"] is False
    assert len(log) == 1
    database = (tmp_path / "app.sqlite3").read_bytes()
    assert b"Turbo Tortoise" not in database
    assert client.get("/api/import/candidates").json()["candidates"][0]["id"] == candidate["id"]


def test_a_hostile_reply_that_invents_things_never_becomes_a_candidate(tmp_path: Path) -> None:
    invented = [
        {
            **GOOD,
            "claim": "Led 40 engineers at Gravy Boat Labs.",
            "source": "Built Python services",
        },
        {**GOOD, "claim": "Built Python services at Initech.", "source": "Built Python services"},
        {**GOOD, "tags": ["kubernetes"]},
        {**GOOD, "source": "Principal Engineer for twenty years"},
    ]
    with chat_server(reply(*invented)) as (base_url, _):
        response = run(make(tmp_path, base_url))

    body = response.json()
    assert body["candidates"] == []
    assert body["dropped"] == {
        "number_not_in_source": 1,
        "name_not_in_source": 1,
        "tag_not_in_source": 1,
        "source_not_in_resume": 1,
    }


def test_a_reply_with_an_extra_field_or_a_level_is_a_schema_failure(tmp_path: Path) -> None:
    sneaky = {**GOOD, "verified": True, "level": "expert"}
    with chat_server(reply(sneaky)) as (base_url, _):
        body = run(make(tmp_path, base_url)).json()

    assert body["candidates"] == [] and body["status"] == "not_run"
    assert body["failure"] is not None


def test_approving_writes_one_unverified_local_only_fact_and_nothing_else(
    tmp_path: Path,
) -> None:
    with chat_server(reply(GOOD)) as (base_url, _):
        client = make(tmp_path, base_url)
        candidate = run(client).json()["candidates"][0]

    approved = send(client, "POST", f"/api/import/candidates/{candidate['id']}/approve")

    body = approved.json()
    assert approved.status_code == 200
    fact = body["fact"]
    assert fact["id"] == "F-0001" and fact.get("verified_on") is None
    assert fact["share"] == "local_only" and fact["tags"] == [
        {"name": "python", "level": "familiar"}
    ]
    assert body["candidate"]["state"] == "approved"
    bank = load_bank(tmp_path / "private" / "bank.yaml")
    assert [f.id for f in bank.facts] == ["F-0001"] and bank.unverified_ids() == ["F-0001"]
    assert client.get("/api/import/candidates").json()["candidates"] == []
    again = send(client, "POST", f"/api/import/candidates/{candidate['id']}/approve")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "candidate_not_pending"
    assert len(load_bank(tmp_path / "private" / "bank.yaml").facts) == 1


def test_rejecting_keeps_it_out_of_the_bank(tmp_path: Path) -> None:
    with chat_server(reply(GOOD)) as (base_url, _):
        client = make(tmp_path, base_url)
        candidate = run(client).json()["candidates"][0]

    rejected = send(client, "POST", f"/api/import/candidates/{candidate['id']}/reject")

    assert rejected.json()["state"] == "rejected"
    assert not (tmp_path / "private" / "bank.yaml").exists()
    assert (
        send(client, "POST", f"/api/import/candidates/{candidate['id']}/approve").status_code == 409
    )


def test_no_route_can_verify_and_an_unknown_candidate_is_a_404(tmp_path: Path) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")

    assert (
        send(client, "POST", "/api/import/candidates/C-" + "a" * 16 + "/approve").status_code == 404
    )
    assert send(client, "POST", "/api/import/candidates/not-an-id/approve").status_code == 422
    assert (
        client.request("POST", "/api/import/candidates/C-" + "a" * 16 + "/approve").status_code
        == 403
    )


def test_a_claim_already_in_the_bank_is_not_proposed(tmp_path: Path) -> None:
    with chat_server(reply(GOOD)) as (base_url, _):
        client = make(tmp_path, base_url)
        first = run(client).json()["candidates"][0]
        send(client, "POST", f"/api/import/candidates/{first['id']}/approve")
        second = run(client).json()

    assert second["candidates"] == [] and second["dropped"] == {"already_in_bank": 1}


def test_a_repeated_import_does_not_double_the_pending_list(tmp_path: Path) -> None:
    with chat_server(reply(GOOD)) as (base_url, _):
        client = make(tmp_path, base_url)
        run(client)
        second = run(client).json()

    assert second["candidates"] == [] and second["dropped"] == {"already_pending": 1}
    assert len(client.get("/api/import/candidates").json()["candidates"]) == 1


def test_injection_text_in_the_resume_stays_inside_the_data_block(tmp_path: Path) -> None:
    with chat_server(reply()) as (base_url, log):
        run(make(tmp_path, base_url), HOSTILE)

    (request,) = log
    system, user = (m["content"] for m in request.json["messages"])
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in system
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in user
    assert "tools" not in request.json
    capabilities = Capabilities(
        context_tokens=8192,
        strict_schema=True,
        local=True,
        cost_per_mtok=CostPerMtok(input=0, output=0),
    )
    expected = build_prompt(Stage.IMPORT, "x", [], capabilities, ResumeImportOutput).system
    assert system == expected


def test_a_hosted_backend_needs_the_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CYPRESS_CREEK_TEST_API_KEY", "recognizable-test-key-" + "z" * 24)
    client = make(
        tmp_path,
        "https://api.example.invalid/v1",
        allow_remote=True,
        api_key_env="CYPRESS_CREEK_TEST_API_KEY",  # pragma: allowlist secret
        input_usd_per_mtok=0.1,
        output_usd_per_mtok=0.5,
    )

    response = run(client)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "hosted_backend_not_confirmed"


def test_a_down_backend_gives_not_run_and_no_candidates(tmp_path: Path) -> None:
    body = run(make(tmp_path, "http://127.0.0.1:1/v1")).json()

    assert body["status"] == "not_run" and body["candidates"] == []


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"backend": "openai_compatible"}, 422),
        ({"text": "", "backend": "openai_compatible"}, 422),
        ({"text": "x", "backend": "someone-else"}, 422),
        ({"text": "x", "backend": "openai_compatible", "extra": 1}, 422),
        ({"text": " \n ", "backend": "openai_compatible"}, 422),
    ],
)
def test_bad_requests_get_typed_errors(
    tmp_path: Path, payload: dict[str, object], status: int
) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")

    assert post_json(client, "/api/import/resume", payload).status_code == status


def test_a_request_without_the_csrf_token_and_a_wrong_media_type_are_refused(
    tmp_path: Path,
) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")

    plain = client.post("/api/import/resume", json={"text": "x", "backend": "openai_compatible"})
    wrong = client.post(
        "/api/import/resume",
        content=b"x",
        headers=csrf_headers(client, {"content-type": "text/plain"}),
    )

    assert plain.status_code == 403 and wrong.status_code == 415


def test_an_oversized_json_body_is_refused_before_the_route(tmp_path: Path) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")

    response = post_json(
        client,
        "/api/import/resume",
        {"text": "a" * (2 * 1024 * 1024), "backend": "openai_compatible"},
    )

    assert response.status_code == 413


def test_a_pdf_resume_goes_through_the_extractor_and_hidden_text_never_reaches_the_model(
    tmp_path: Path,
) -> None:
    with chat_server(reply()) as (base_url, log):
        client = make(tmp_path, base_url)
        headers = csrf_headers(client, {"content-type": "application/pdf"})
        response = client.post(
            "/api/import/resume?backend=openai_compatible",
            content=(PDFS / "white_on_white.pdf").read_bytes(),
            headers=headers,
        )

    assert response.status_code == 200 and response.json()["status"] == "done"
    (request,) = log
    user = request.json["messages"][1]["content"]
    assert "Senior Data Engineer" in user and "ZXQ-PAYLOAD" not in user


def test_a_pdf_that_cannot_be_read_is_a_typed_error_and_calls_no_model(tmp_path: Path) -> None:
    with chat_server(reply()) as (base_url, log):
        client = make(tmp_path, base_url)
        headers = csrf_headers(client, {"content-type": "application/pdf"})
        response = client.post(
            "/api/import/resume?backend=openai_compatible",
            content=(PDFS / "encrypted.pdf").read_bytes(),
            headers=headers,
        )

    assert response.status_code == 422 and response.json()["error"]["code"] == "pdf_encrypted"
    assert log == []


def test_the_pending_table_holds_no_resume_text(tmp_path: Path) -> None:
    with chat_server(reply(GOOD)) as (base_url, _):
        run(make(tmp_path, base_url))

    with closing(sqlite3.connect(tmp_path / "app.sqlite3")) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(fact_candidate)")]
    assert "resume_text" not in columns and "text" not in columns
