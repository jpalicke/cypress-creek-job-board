# ABOUTME: Drives the health, providers, session and static bundle routes of the real app.
# ABOUTME: Reachability is checked against a real closed port and a real loopback server.
from pathlib import Path

import pytest
from api_support import ApiClient
from http_support import http_server

from cypress_creek.api.app import create_app
from cypress_creek.api.routes.health import check_reachability
from cypress_creek.config import ProviderSettings

KEY_ENV = "CYPRESS_CREEK_TEST_API_KEY"
KEY_VALUE = "recognizable-test-key-" + "z" * 24


def settings_for(base_url: str, **changes: object) -> ProviderSettings:
    fields: dict[str, object] = {
        "provider": "ollama",
        "model": "qwen3.5:0.8b",
        "base_url": base_url,
    }
    fields.update(changes)
    return ProviderSettings.model_validate(fields)


def test_health_reports_a_backend_that_cannot_be_reached() -> None:
    client = ApiClient(create_app(settings_for("http://127.0.0.1:1")))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "backends": [{"provider": "ollama", "model": "qwen3.5:0.8b", "reachable": "unreachable"}],
    }


def test_health_reports_a_backend_that_answers() -> None:
    with http_server() as (port, requests):
        client = ApiClient(create_app(settings_for(f"http://127.0.0.1:{port}")))

        response = client.get("/api/health")

    assert response.json()["backends"][0]["reachable"] == "reachable"
    assert requests.methods == ["GET"]


def test_health_works_with_no_backend_configured() -> None:
    client = ApiClient(create_app(None))

    assert client.get("/api/health").json() == {"status": "ok", "backends": []}
    assert client.get("/api/providers").json() == {"providers": []}


def test_providers_lists_capabilities() -> None:
    client = ApiClient(create_app(settings_for("http://127.0.0.1:1", context_tokens=4096)))

    response = client.get("/api/providers")

    assert response.status_code == 200
    assert response.json() == {
        "providers": [
            {
                "provider": "ollama",
                "model": "qwen3.5:0.8b",
                "local": True,
                "strict_schema": True,
                "context_tokens": 4096,
                "cost_per_mtok": {"input": 0.0, "output": 0.0},
            }
        ]
    }


def test_no_answer_ever_contains_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, KEY_VALUE)
    app = create_app(settings_for("http://127.0.0.1:1", api_key_env=KEY_ENV))
    client = ApiClient(app)

    answers = [
        client.get("/api/providers"),
        client.get("/api/health"),
        client.get("/api/session"),
        client.get("/api/nothing"),
    ]

    for answer in answers:
        assert KEY_VALUE not in answer.text
        assert KEY_ENV not in answer.text


def test_the_built_bundle_is_served_when_it_exists(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>bundle</html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    client = ApiClient(create_app(None, static_dir=tmp_path))

    assert client.get("/").text == "<html>bundle</html>"
    assert client.get("/app.js").text == "console.log(1)"
    assert client.get("/api/health").status_code == 200
    missing = client.get("/api/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_the_bundle_cannot_be_escaped_by_a_path(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    client = ApiClient(create_app(None, static_dir=site))

    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
        assert "secret" not in client.get(path).text


def test_without_a_bundle_the_root_is_a_typed_404(tmp_path: Path) -> None:
    client = ApiClient(create_app(None, static_dir=tmp_path / "absent"))

    response = client.get("/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_docs_and_schema_routes_are_off() -> None:
    client = ApiClient(create_app(None))

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_a_backend_that_cannot_be_probed_yet_is_not_checked() -> None:
    hosted = ProviderSettings(provider="hosted-example", model="m", api_key_env=KEY_ENV)

    assert check_reachability(hosted) == "not_checked"
