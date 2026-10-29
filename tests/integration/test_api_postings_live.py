# ABOUTME: Live checks of the posting and analyze routes: a real public page and the CI model.
# ABOUTME: An unreachable network or Ollama fails these tests loudly, they are never skipped.
from pathlib import Path

import pytest
from api_support import ApiClient, post_json

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings

ROOT = Path(__file__).parent.parent.parent
BANK = ROOT / "evals" / "bank" / "sample_bank.yaml"
POSTING = (
    "Data Engineer at Fictional Widgets.\n"
    "Requirements: three years of Python experience and strong PostgreSQL skills.\n"
    "Nice to have: Kubernetes."
)


def client_for(tmp_path: Path, settings: ProviderSettings) -> ApiClient:
    return ApiClient(
        create_app(settings, static_dir=None, database_path=tmp_path / "db.sqlite3", bank_path=BANK)
    )


@pytest.mark.needs_network
def test_a_real_public_page_is_fetched_and_turned_into_a_posting(tmp_path: Path) -> None:
    settings = ProviderSettings(provider="ollama", model="qwen3.5:0.8b")
    client = client_for(tmp_path, settings)

    response = post_json(client, "/api/postings", {"source": "link", "url": "https://example.com/"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert "Example Domain" in body["text"]
    assert body["source"] == "link"
    assert body["origin_url"] == "https://example.com/"


@pytest.mark.live
def test_a_pasted_posting_is_analyzed_and_the_stored_report_matches(tmp_path: Path) -> None:
    settings = ProviderSettings(provider="ollama", model="qwen3.5:0.8b", context_tokens=8192)
    client = client_for(tmp_path, settings)
    posting_id = post_json(client, "/api/postings", {"source": "paste", "text": POSTING}).json()[
        "id"
    ]

    analysis = post_json(client, f"/api/postings/{posting_id}/analyze", {"backend": "ollama"})

    assert analysis.status_code == 200, analysis.text
    stored = client.get(f"/api/reports/{analysis.json()['report_id']}")
    assert stored.json()["report"] == analysis.json()["report"]
    report = analysis.json()["report"]
    assert report["status"] in ("complete", "incomplete")
    assert not any("provider_unavailable" in reason for reason in report["incomplete_reasons"])
    assert report["provenance"]["usage"]["input_tokens"] > 0
