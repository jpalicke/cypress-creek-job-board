# ABOUTME: Drives the real FastAPI app through its security layer over httpx's ASGI transport.
# ABOUTME: Covers the CSRF token on writes, the Host check, absent CORS and the typed error shape.
import pytest
from api_support import ApiClient
from fastapi import APIRouter

from cypress_creek.api.app import create_app
from cypress_creek.config import ProviderSettings

TOKEN_HEADER = "X-CSRF-Token"
PORT = 5309

write_probe = APIRouter()


@write_probe.post("/api/write-probe")
def accept_write() -> dict[str, bool]:
    return {"accepted": True}


@write_probe.get("/api/boom")
def explode() -> dict[str, bool]:
    raise RuntimeError("secret-internal-detail /home/someone/file.py")


def make_settings() -> ProviderSettings:
    return ProviderSettings(provider="ollama", model="qwen3.5:0.8b", base_url="http://127.0.0.1:1")


@pytest.fixture
def client() -> ApiClient:
    app = create_app(make_settings())
    app.include_router(write_probe)
    return ApiClient(app)


def csrf_token(client: ApiClient) -> str:
    return str(client.get("/api/session").json()["csrf_token"])


def test_a_write_without_the_token_is_rejected(client: ApiClient) -> None:
    response = client.post("/api/write-probe")

    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "csrf_token_invalid", "message": "Missing or invalid CSRF token."}
    }


def test_a_write_with_the_right_token_passes_the_security_layer(client: ApiClient) -> None:
    response = client.post("/api/write-probe", headers={TOKEN_HEADER: csrf_token(client)})

    assert response.status_code == 200
    assert response.json() == {"accepted": True}


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_write_method_needs_the_token(client: ApiClient, method: str) -> None:
    router = APIRouter()
    router.add_api_route("/api/method-probe", accept_write, methods=[method])
    client.app.include_router(router)

    refused = client.request(method, "/api/method-probe")
    allowed = client.request(
        method, "/api/method-probe", headers={TOKEN_HEADER: csrf_token(client)}
    )

    assert refused.status_code == 403
    assert allowed.status_code == 200


def test_a_wrong_token_is_rejected(client: ApiClient) -> None:
    right = csrf_token(client)
    wrong = right[:-1] + ("A" if right[-1] != "A" else "B")

    response = client.post("/api/write-probe", headers={TOKEN_HEADER: wrong})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_token_invalid"


def test_a_token_of_another_server_is_rejected() -> None:
    first = create_app(make_settings())
    second = create_app(make_settings())
    first.include_router(write_probe)
    second.include_router(write_probe)
    one, two = ApiClient(first), ApiClient(second)
    token = csrf_token(one)
    response = two.post("/api/write-probe", headers={TOKEN_HEADER: token})

    assert response.status_code == 403


def test_the_session_route_sets_no_cookie(client: ApiClient) -> None:
    response = client.get("/api/session")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers


def test_reads_need_no_token(client: ApiClient) -> None:
    assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}"])
def test_the_loopback_hosts_are_accepted(client: ApiClient, host: str) -> None:
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        f"evil.example:{PORT}",
        "127.0.0.1",
        "localhost",
        "127.0.0.1:5310",
        "localhost:80",
        f"127.0.0.1.evil.example:{PORT}",
        f"127.0.0.1:{PORT}.evil.example",
        f"[::1]:{PORT}",
        "",
    ],
)
def test_any_other_host_is_rejected(client: ApiClient, host: str) -> None:
    response = client.get("/api/health", headers={"Host": host})

    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "host_not_allowed", "message": "Host header is not allowed."}
    }


def test_the_host_check_runs_before_the_token_check(client: ApiClient) -> None:
    response = client.post("/api/write-probe", headers={"Host": "evil.example"})

    assert response.json()["error"]["code"] == "host_not_allowed"


def test_the_host_check_covers_unknown_paths(client: ApiClient) -> None:
    response = client.get("/nothing-here", headers={"Host": "evil.example"})

    assert response.status_code == 403


def test_no_cors_header_appears_on_any_answer(client: ApiClient) -> None:
    origin = {"Origin": "https://evil.example"}
    answers = [
        client.get("/api/health", headers=origin),
        client.post("/api/write-probe", headers=origin),
        client.get("/nothing-here", headers=origin),
        client.options(
            "/api/write-probe",
            headers={**origin, "Access-Control-Request-Method": "POST"},
        ),
    ]

    for answer in answers:
        assert not [name for name in answer.headers if name.lower().startswith("access-control-")]


def test_a_preflight_is_not_answered_with_permissions(client: ApiClient) -> None:
    response = client.options(
        "/api/write-probe",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_an_unknown_route_is_a_typed_404(client: ApiClient) -> None:
    response = client.get("/api/nothing-here")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not found."}}


def test_an_unexpected_failure_is_a_typed_500_without_internals(client: ApiClient) -> None:
    response = client.get("/api/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "The server hit an unexpected error."}
    }
    assert "secret-internal-detail" not in response.text
    assert "Traceback" not in response.text
