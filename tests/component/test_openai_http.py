# ABOUTME: Tests the openai_compatible adapter over real HTTP against a loopback chat server.
# ABOUTME: Covers the URL, headers, body, status mapping and reply parsing that the key will use.
import pytest
from chat_server import Reply, chat_server, json_reply
from pydantic import BaseModel

from cypress_creek.config import ConfigError, parse_settings
from cypress_creek.providers import (
    ContextTruncated,
    OpenAICompatibleProvider,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
)

KEY = "sk-test-SECRET-1234567890"  # pragma: allowlist secret
ENV = {"TEST_OPENAI_KEY": KEY}


class Answer(BaseModel):
    text: str


def _provider(base_url: str, **extra: object) -> OpenAICompatibleProvider:
    settings = parse_settings(
        {
            "provider": "openai_compatible",
            "model": "test-model",
            "base_url": base_url,
            "api_key_env": "TEST_OPENAI_KEY",  # pragma: allowlist secret
            "context_tokens": 4096,
            **extra,
        }
    )
    return OpenAICompatibleProvider(settings, environ=ENV)


def _completion(content: str = '{"text": "hi"}', **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 4},
    }
    body.update(extra)
    return body


def test_a_good_reply_is_parsed_and_the_request_has_the_documented_shape() -> None:
    with chat_server(json_reply(_completion())) as (base_url, log):
        result = _provider(base_url).complete_structured("SYS", "DATA", Answer, 50)

    assert result.parsed == Answer(text="hi")
    assert (result.usage.input_tokens, result.usage.output_tokens) == (30, 4)
    (request,) = log
    assert request.path == "/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["content-type"] == "application/json"
    body = request.json
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["max_tokens"] == 50
    assert KEY not in request.body.decode("utf-8")


def test_429_is_rate_limited_with_the_retry_after_seconds() -> None:
    with (
        chat_server(Reply(429, b"{}", {"Retry-After": "3"})) as (base_url, _),
        pytest.raises(RateLimited) as caught,
    ):
        _provider(base_url).complete_structured("s", "d", Answer, 10)
    assert caught.value.retry_after_seconds == 3.0
    assert caught.value.request_attempted is True


def test_a_400_naming_the_context_length_is_context_truncated() -> None:
    body = {"error": {"code": "context_length_exceeded", "message": "too long"}}
    with (
        chat_server(json_reply(body, status=400)) as (base_url, _),
        pytest.raises(ContextTruncated) as caught,
    ):
        _provider(base_url).complete_structured("s", "d", Answer, 10)
    assert caught.value.context_tokens == 4096
    assert "truncation signature" not in str(caught.value)


def test_the_recorded_lm_studio_overflow_reply_is_context_truncated() -> None:
    # The error body LM Studio 0.4.17 returned for a prompt longer than the loaded context
    # (8192), recorded by Joe P on 2026-10-30. The error is a plain string, not an object.
    body = {
        "error": (
            "The number of tokens to keep from the initial prompt is greater than the context "
            "length (n_keep: 20015>= n_ctx: 8192). Try to load the model with a larger context "
            "length, or provide a shorter input."
        )
    }
    with (
        chat_server(json_reply(body, status=400)) as (base_url, _),
        pytest.raises(ContextTruncated) as caught,
    ):
        _provider(base_url).complete_structured("s", "d", Answer, 10)
    assert caught.value.context_tokens == 4096


def test_another_status_is_provider_unavailable_and_never_shows_the_key() -> None:
    reply = Reply(401, f"bad key {KEY}".encode())
    with chat_server(reply) as (base_url, _), pytest.raises(ProviderUnavailable) as caught:
        _provider(base_url).complete_structured("s", "d", Answer, 10)
    assert "HTTP 401" in caught.value.reason
    assert KEY not in str(caught.value)


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]"])
def test_a_reply_that_is_not_a_json_object_is_provider_unavailable(body: bytes) -> None:
    with chat_server(Reply(200, body)) as (base_url, _), pytest.raises(ProviderUnavailable):
        _provider(base_url).complete_structured("s", "d", Answer, 10)


def test_a_reply_off_the_schema_is_a_schema_violation_that_carries_usage() -> None:
    with (
        chat_server(json_reply(_completion('{"wrong": 1}'))) as (base_url, _),
        pytest.raises(SchemaViolation) as caught,
    ):
        _provider(base_url).complete_structured("s", "d", Answer, 10)
    assert caught.value.usage is not None
    assert caught.value.usage.input_tokens == 30


def test_a_refusal_without_usage_is_still_a_refusal() -> None:
    body = {"choices": [{"finish_reason": "stop", "message": {"refusal": "no"}}]}
    with chat_server(json_reply(body)) as (base_url, _), pytest.raises(Refusal):
        _provider(base_url).complete_structured("s", "d", Answer, 10)


def test_a_remote_url_that_is_not_https_is_refused_so_the_key_is_not_sent_in_clear() -> None:
    settings = parse_settings(
        {
            "provider": "openai_compatible",
            "model": "m",
            "base_url": "http://api.example.com/v1",
            "allow_remote": True,
            "api_key_env": "TEST_OPENAI_KEY",  # pragma: allowlist secret
            "input_usd_per_mtok": 1,
            "output_usd_per_mtok": 1,
        }
    )
    with pytest.raises(ConfigError, match="https"):
        OpenAICompatibleProvider(settings, environ=ENV)
