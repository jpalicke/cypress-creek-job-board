# ABOUTME: Drives the posting, analyze, estimate and report routes of the real app and a real store.
# ABOUTME: The backend is a real address nothing listens on, so a down backend is the real thing.
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from api_support import ApiClient, csrf_headers, post_json
from http_support import http_server

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings

ROOT = Path(__file__).parent.parent.parent
BANK = ROOT / "evals" / "bank" / "sample_bank.yaml"
POSTING = "A backend role requires three years of Python experience and PostgreSQL."
KEY_ENV = "CYPRESS_CREEK_TEST_API_KEY"
KEY_VALUE = "recognizable-test-key-" + "z" * 24


def make_client(tmp_path: Path, **settings: object) -> ApiClient:
    fields: dict[str, object] = {
        "provider": "ollama",
        "model": "qwen3.5:0.8b",
        "base_url": "http://127.0.0.1:1",
    }
    fields.update(settings)
    app = create_app(
        ProviderSettings.model_validate(fields),
        static_dir=None,
        database_path=tmp_path / "app.sqlite3",
        bank_path=BANK,
    )
    return ApiClient(app)


def paste(client: ApiClient, text: str = POSTING) -> str:
    response = post_json(client, "/api/postings", {"source": "paste", "text": text})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.fixture
def client(tmp_path: Path) -> ApiClient:
    return make_client(tmp_path)


def test_analyze_returns_an_incomplete_report_when_the_backend_is_down(client: ApiClient) -> None:
    posting_id = paste(client)

    response = post_json(client, f"/api/postings/{posting_id}/analyze", {"backend": "ollama"})

    assert response.status_code == 200
    body = response.json()
    report = body["report"]
    assert report["status"] == "incomplete"
    assert report["score"] is None
    assert report["rows"] == []
    assert "provider_unavailable" in report["incomplete_reasons"][0]
    stored = client.get(f"/api/reports/{body['report_id']}")
    assert stored.status_code == 200
    assert stored.json()["report"] == report
    assert stored.json()["posting_id"] == posting_id


def test_paste_returns_normalized_text_and_a_control_character_warning(
    client: ApiClient,
) -> None:
    response = post_json(
        client, "/api/postings", {"source": "paste", "text": "Python​   and\r\nSQL"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "Python and\nSQL"
    assert body["warnings"] == [{"kind": "control_chars_stripped", "count": 1}]
    assert body["id"].startswith("post-")
    assert body["source"] == "paste"
    assert len(body["text_hash"]) == 64


def test_blank_and_over_long_text_are_typed_errors(client: ApiClient) -> None:
    blank = post_json(client, "/api/postings", {"source": "paste", "text": " \n "})
    long = post_json(client, "/api/postings", {"source": "paste", "text": "a" * 50_001})

    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "empty_posting"
    assert long.status_code == 413
    assert long.json()["error"]["code"] == "posting_too_long"


def test_a_malformed_request_is_a_typed_422_without_the_input(client: ApiClient) -> None:
    echoed = "do-not-echo-this-value"
    response = post_json(client, "/api/postings", {"source": "nonsense", "text": echoed})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert echoed not in response.text
    missing = post_json(client, "/api/postings", {"source": "paste"})
    assert missing.json()["error"]["code"] == "invalid_request"
    both = post_json(
        client, "/api/postings", {"source": "paste", "text": "x", "url": "https://a.b"}
    )
    assert both.json()["error"]["code"] == "invalid_request"


def test_a_link_to_a_private_address_is_blocked_without_contacting_it(
    client: ApiClient,
) -> None:
    with http_server() as (port, requests):
        response = post_json(
            client, "/api/postings", {"source": "link", "url": f"http://127.0.0.1:{port}/job"}
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "blocked_by_policy"
    assert body["error"]["details"][0]["field"] == "reason"
    assert requests.received == []
    assert "127.0.0.1" not in response.text


def test_the_content_type_decides_how_the_body_is_read(client: ApiClient) -> None:
    text = client.post(
        "/api/postings",
        content=b"hello",
        headers=csrf_headers(client, {"content-type": "text/plain"}),
    )

    assert text.status_code == 415
    assert text.json()["error"]["code"] == "unsupported_media_type"


def test_a_pdf_is_checked_for_size_and_type_before_anything_reads_it(client: ApiClient) -> None:
    headers = csrf_headers(client, {"content-type": "application/pdf"})
    not_pdf = client.post("/api/postings", content=b"<html>not a pdf</html>", headers=headers)
    oversize = client.post(
        "/api/postings", content=b"%PDF-" + b"0" * (10 * 1024 * 1024), headers=headers
    )
    plausible = client.post("/api/postings", content=b"%PDF-1.7\n%%EOF", headers=headers)

    assert not_pdf.status_code == 422
    assert not_pdf.json()["error"]["code"] == "invalid_pdf"
    assert oversize.status_code == 413
    assert oversize.json()["error"]["code"] == "payload_too_large"
    assert plausible.status_code == 501
    assert plausible.json()["error"]["code"] == "pdf_extraction_unavailable"


def test_a_json_body_over_the_limit_is_refused(client: ApiClient) -> None:
    huge = client.post(
        "/api/postings",
        content=b'{"source":"paste","text":"' + b"a" * (1024 * 1024) + b'"}',
        headers=csrf_headers(client, {"content-type": "application/json"}),
    )

    assert huge.status_code == 413
    assert huge.json()["error"]["code"] == "payload_too_large"


def test_a_chunked_body_is_counted_and_accepted_within_the_limit(client: ApiClient) -> None:
    async def small() -> AsyncIterator[bytes]:
        yield b'{"source":"paste",'
        yield b'"text":"x"}'

    async def endless() -> AsyncIterator[bytes]:
        for _ in range(40):
            yield b" " * (64 * 1024)

    headers = csrf_headers(client, {"content-type": "application/json"})
    accepted = client.post("/api/postings", content=small(), headers=headers)
    refused = client.post("/api/postings", content=endless(), headers=headers)

    assert accepted.status_code == 201
    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "payload_too_large"


def test_analyze_needs_a_known_posting_and_the_configured_backend(client: ApiClient) -> None:
    missing = post_json(client, "/api/postings/post-nope/analyze", {"backend": "ollama"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    posting_id = paste(client)
    wrong = post_json(client, f"/api/postings/{posting_id}/analyze", {"backend": "anthropic"})
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "unknown_backend"
    absent = post_json(client, f"/api/postings/{posting_id}/analyze", {})
    assert absent.json()["error"]["code"] == "invalid_request"


def test_the_estimate_is_available_before_any_spend(client: ApiClient) -> None:
    posting_id = paste(client)

    response = client.get(f"/api/postings/{posting_id}/estimate")

    assert response.status_code == 200
    body = response.json()
    assert body["requests"] == 1
    assert body["input_tokens"] > 0
    assert body["usd"] == 0
    assert body["covers"] == "extraction"
    assert client.get("/api/postings/post-nope/estimate").status_code == 404


def test_a_budget_that_cannot_fit_stops_the_estimate_and_the_analysis(tmp_path: Path) -> None:
    client = make_client(tmp_path, max_input_tokens=1)
    posting_id = paste(client)

    estimate = client.get(f"/api/postings/{posting_id}/estimate")
    analysis = post_json(client, f"/api/postings/{posting_id}/analyze", {"backend": "ollama"})

    assert estimate.status_code == 409
    assert estimate.json()["error"]["code"] == "budget_exceeded"
    assert analysis.status_code == 409
    assert analysis.json()["error"]["code"] == "budget_exceeded"


def test_a_stored_report_lists_its_validator_verdicts_without_offending_text(
    client: ApiClient,
) -> None:
    posting_id = paste(client)
    report_id = post_json(
        client, f"/api/postings/{posting_id}/analyze", {"backend": "ollama"}
    ).json()["report_id"]

    body = client.get(f"/api/reports/{report_id}").json()

    assert {v["validator"] for v in body["validator_verdicts"]} == {"V4", "V5", "V9"}
    assert all(v["passed"] for v in body["validator_verdicts"])
    assert all(
        set(v) == {"stage", "subject", "validator", "passed", "reason"}
        for v in body["validator_verdicts"]
    )
    assert client.get("/api/reports/rep-nope").status_code == 404


def test_no_answer_contains_a_key_or_a_stack_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(KEY_ENV, KEY_VALUE)
    client = make_client(tmp_path, api_key_env=KEY_ENV)
    posting_id = paste(client)
    answers = [
        post_json(client, f"/api/postings/{posting_id}/analyze", {"backend": "ollama"}),
        client.get(f"/api/postings/{posting_id}/estimate"),
        post_json(client, "/api/postings", {"source": "link", "url": "http://127.0.0.1:9/"}),
        post_json(client, "/api/postings", {"source": "paste", "text": ""}),
        post_json(client, "/api/postings/post-nope/analyze", {"backend": "ollama"}),
        client.get("/api/reports/rep-nope"),
        client.get("/api/facts"),
        post_json(client, "/api/facts/validate", {"yaml": "facts: ["}),
    ]

    for answer in answers:
        assert KEY_VALUE not in answer.text
        assert KEY_ENV not in answer.text
        assert "Traceback" not in answer.text
        assert 'File "' not in answer.text
