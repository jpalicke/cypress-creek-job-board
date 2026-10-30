# ABOUTME: Drives POST /api/reports/{id}/suggestions on the real app with a hand written reply.
# ABOUTME: A real loopback chat server plays the reply, so the draft stage and validators run.
import json
from pathlib import Path

import pytest
from api_support import ApiClient, post_json
from chat_server import Reply, chat_server, json_reply
from eval_support import Got, report_for

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings
from cypress_creek.ingest.build import build_posting
from cypress_creek.ingest.models import Extractor, PostingSource
from cypress_creek.pipeline.report import GapReport
from cypress_creek.scoring.support import Support
from cypress_creek.storage.db import connect, migrate
from cypress_creek.storage.repository import PostingStore, ReportStore

ROOT = Path(__file__).parent.parent.parent
BANK = ROOT / "evals" / "bank" / "sample_bank.yaml"
POSTING = "You must know Python.\nExperience with Go is preferred.\n"
CLAIM = "Backend Developer at Gravy Boat Labs, where I built and ran Python services."
KEY_ENV = "CYPRESS_CREEK_TEST_API_KEY"


def reply(*sentences: tuple[str, list[str]]) -> Reply:
    output = {
        "schema_version": 1,
        "sentences": [{"text": text, "fact_ids": ids} for text, ids in sentences],
    }
    return json_reply(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(output)},
                }
            ],
            "usage": {"prompt_tokens": 40, "completion_tokens": 20},
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
    app = create_app(
        ProviderSettings.model_validate(fields),
        static_dir=None,
        database_path=tmp_path / "app.sqlite3",
        bank_path=BANK,
    )
    return ApiClient(app)


def store(tmp_path: Path) -> str:
    connection = connect(tmp_path / "app.sqlite3")
    migrate(connection)
    connection.close()
    report: GapReport = report_for(
        POSTING,
        [
            Got("You must know Python.", Support.STRONG, fact_ids=("F-0001",)),
            Got("Experience with Go is preferred.", Support.NONE),
        ],
    )
    PostingStore(tmp_path / "app.sqlite3").add(
        build_posting(
            POSTING,
            PostingSource.PASTE,
            Extractor(name="paste", version="1"),
            posting_id=report.posting_id,
        )
    )
    return ReportStore(tmp_path / "app.sqlite3").add(report, [])


def ask(client: ApiClient, report_id: str, requirement: str, **extra: object) -> object:
    body = {"requirement_id": requirement, "backend": "openai_compatible", **extra}
    return post_json(client, f"/api/reports/{report_id}/suggestions", body)


def test_a_drafted_requirement_returns_each_sentence_with_verdicts_and_the_cited_claim(
    tmp_path: Path,
) -> None:
    with chat_server(reply((CLAIM, ["F-0001"]), ("I led a team of 40 engineers.", ["F-0001"]))) as (
        base_url,
        log,
    ):
        client = make(tmp_path, base_url)
        report_id = store(tmp_path)
        response = ask(client, report_id, "R-1")

    assert response.status_code == 200  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert body["status"] == "drafted"
    assert body["needs_human_review"] is True
    clean, flagged = body["sentences"]
    assert clean["text"] == CLAIM and clean["passed"] is True and clean["fact_ids"] == ["F-0001"]
    assert flagged["passed"] is False
    assert any(not v["passed"] for v in flagged["verdicts"])
    assert all(set(v) == {"validator", "passed", "reason"} for v in flagged["verdicts"])
    assert body["facts"] == [{"id": "F-0001", "claim": CLAIM}]
    assert len(log) == 1


def test_a_requirement_with_no_support_is_never_drafted_and_calls_no_model(
    tmp_path: Path,
) -> None:
    with chat_server(reply((CLAIM, ["F-0001"]))) as (base_url, log):
        client = make(tmp_path, base_url)
        report_id = store(tmp_path)
        response = ask(client, report_id, "R-2")

    body = response.json()  # type: ignore[attr-defined]
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert body["status"] == "no_support"
    assert body["sentences"] == [] and body["facts"] == []
    assert log == []


def test_a_down_backend_is_not_run_with_a_failure_label(tmp_path: Path) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")
    report_id = store(tmp_path)

    response = ask(client, report_id, "R-1")

    body = response.json()  # type: ignore[attr-defined]
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert body["status"] == "not_run" and body["sentences"] == []


def test_an_unknown_report_or_requirement_is_a_typed_404(tmp_path: Path) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")
    report_id = store(tmp_path)

    missing_report = ask(client, "no-such-report", "R-1")
    missing_row = ask(client, report_id, "R-9")

    assert missing_report.status_code == 404  # type: ignore[attr-defined]
    assert missing_row.status_code == 404  # type: ignore[attr-defined]
    assert missing_row.json()["error"]["code"] == "not_found"  # type: ignore[attr-defined]


def test_a_request_without_the_csrf_token_is_refused(tmp_path: Path) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")
    report_id = store(tmp_path)

    response = client.post(
        f"/api/reports/{report_id}/suggestions",
        json={"requirement_id": "R-1", "backend": "openai_compatible"},
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"requirement_id": "R-1"},
        {"requirement_id": "../x", "backend": "openai_compatible"},
        {"requirement_id": "R-1", "backend": "openai_compatible", "extra": 1},
        {"requirement_id": "R-1", "backend": "someone-else"},
    ],
)
def test_a_bad_request_body_is_refused_with_a_typed_error(
    tmp_path: Path, body: dict[str, object]
) -> None:
    client = make(tmp_path, "http://127.0.0.1:1/v1")
    report_id = store(tmp_path)

    response = post_json(client, f"/api/reports/{report_id}/suggestions", body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"invalid_request", "unknown_backend"}


def test_a_hosted_backend_needs_the_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(KEY_ENV, "recognizable-test-key-" + "z" * 24)
    client = make(
        tmp_path,
        "https://api.example.invalid/v1",
        allow_remote=True,
        api_key_env=KEY_ENV,
        input_usd_per_mtok=0.1,
        output_usd_per_mtok=0.5,
    )
    report_id = store(tmp_path)

    response = ask(client, report_id, "R-1")

    assert response.status_code == 422  # type: ignore[attr-defined]
    assert response.json()["error"]["code"] == "hosted_backend_not_confirmed"  # type: ignore[attr-defined]
