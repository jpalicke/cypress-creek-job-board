# ABOUTME: Tests the openai_compatible adapter's request value, guards and response reading.
# ABOUTME: Requests are built, never sent, and hostile replies are hand written inputs.
import json
from datetime import date
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from cypress_creek.config import ConfigError, ProviderSettings, parse_settings
from cypress_creek.facts.models import Evidence, EvidenceType, Fact, Kind, Share
from cypress_creek.pipeline.prompt import Stage, build_prompt
from cypress_creek.pipeline.schemas import EntailmentOutput
from cypress_creek.providers import (
    ContextTruncated,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
    get_provider,
)
from cypress_creek.providers.openai_compatible import (
    DEFAULT_BASE_URL,
    OpenAICompatibleProvider,
    check_response_status,
    read_completion,
)

KEY = "sk-test-SECRET-1234567890"  # pragma: allowlist secret
NOTHING_LISTENING = "http://127.0.0.1:9/v1"
HOSTED_ENV = {"TEST_OPENAI_KEY": KEY}


class Answer(BaseModel):
    text: str
    count: int = 0


def _hosted(**extra: object) -> OpenAICompatibleProvider:
    values: dict[str, object] = {
        "provider": "openai_compatible",
        "model": "gpt-6-luna",
        "allow_remote": True,
        "api_key_env": "TEST_OPENAI_KEY",  # pragma: allowlist secret
        "context_tokens": 8192,
        "input_usd_per_mtok": 0.10,
        "output_usd_per_mtok": 0.50,
    }
    values.update(extra)
    return OpenAICompatibleProvider(parse_settings(values), environ=HOSTED_ENV)


def _local(context: int = 2048) -> OpenAICompatibleProvider:
    settings = parse_settings(
        {
            "provider": "openai_compatible",
            "model": "qwen3.5-0.8b",
            "base_url": NOTHING_LISTENING,
            "context_tokens": context,
        }
    )
    return OpenAICompatibleProvider(settings, environ={})


def _fact(fact_id: str, claim: str, share: Share) -> Fact:
    return Fact(
        id=fact_id,
        claim=claim,
        kind=Kind.PROJECT,
        verified_on=date(2026, 1, 1),
        evidence=Evidence(type=EvidenceType.SELF_ATTESTED, pointer="me"),
        share=share,
    )


def _completion(content: Any = '{"text": "hi", "count": 1}', **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {"prompt_tokens": 40, "completion_tokens": 9},
    }
    body.update(overrides)
    return body


def test_a_declared_context_that_is_exceeded_raises_context_truncated_before_any_call() -> None:
    with pytest.raises(ContextTruncated) as caught:
        _local(context=2048).complete_structured("s" * 300, "d" * 7000, Answer, 200)
    assert caught.value.context_tokens == 2048
    assert caught.value.input_tokens > 2048
    assert caught.value.request_attempted is False


def test_the_output_cap_counts_toward_the_window() -> None:
    with pytest.raises(ContextTruncated):
        _local(context=2048).complete_structured("s", "d", Answer, 2048)


def test_system_and_untrusted_data_are_separate_messages_in_order() -> None:
    request = _hosted().build_request(
        "TRUSTED SYSTEM", "<<<POSTING abc>>>\nbody\n<<<END POSTING abc>>>", Answer, 100
    )
    assert [m["role"] for m in request["messages"]] == ["system", "user"]
    assert request["messages"][0]["content"] == "TRUSTED SYSTEM"
    assert "abc" in request["messages"][1]["content"]
    assert "body" not in request["messages"][0]["content"]


def test_a_hosted_request_built_from_a_prompt_carries_only_shareable_facts() -> None:
    provider = _hosted()
    facts = [
        _fact("F-0001", "Wrote Python services", Share.SHAREABLE),
        _fact("F-0002", "Private salary history", Share.LOCAL_ONLY),
    ]
    prompt = build_prompt(
        Stage.ENTAIL, "needs python", facts, provider.capabilities, EntailmentOutput
    )
    request = provider.build_request(prompt.system, prompt.user_message, EntailmentOutput, 100)
    text = json.dumps(request)
    assert "Wrote Python services" in text
    assert "Private salary history" not in text
    assert prompt.boundary_token in request["messages"][1]["content"]
    assert prompt.boundary_token not in request["messages"][0]["content"]
    assert "Wrote Python services" not in request["messages"][0]["content"]


def test_a_loopback_request_may_carry_local_only_facts() -> None:
    provider = _local()
    assert provider.capabilities.local is True
    facts = [_fact("F-0002", "Private salary history", Share.LOCAL_ONLY)]
    prompt = build_prompt(
        Stage.ENTAIL, "needs python", facts, provider.capabilities, EntailmentOutput
    )
    assert "Private salary history" in prompt.facts_block


def test_the_request_asks_for_strict_json_schema_output() -> None:
    request = _hosted().build_request("s", "d", Answer, 100)
    format_ = request["response_format"]
    assert format_["type"] == "json_schema"
    assert format_["json_schema"]["name"] == "Answer"
    assert format_["json_schema"]["strict"] is True
    schema = format_["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["text", "count"]
    assert request["stream"] is False
    assert request["model"] == "gpt-6-luna"


def test_hosted_and_loopback_name_the_output_cap_differently() -> None:
    assert _hosted().build_request("s", "d", Answer, 77)["max_completion_tokens"] == 77
    local = _local().build_request("s", "d", Answer, 77)
    assert local["max_tokens"] == 77
    assert local["temperature"] == 0
    assert "temperature" not in _hosted().build_request("s", "d", Answer, 77)


def test_the_key_goes_in_the_authorization_header_and_never_in_the_body() -> None:
    provider = _hosted()
    assert provider.request_headers()["Authorization"] == f"Bearer {KEY}"
    assert KEY not in json.dumps(provider.build_request("s", "d", Answer, 10))
    assert "Authorization" not in _local().request_headers()


def test_hosted_use_without_a_base_url_defaults_to_the_openai_endpoint() -> None:
    assert DEFAULT_BASE_URL == "https://api.openai.com/v1"
    assert _hosted().endpoint == "https://api.openai.com/v1/chat/completions"


def test_the_default_endpoint_needs_allow_remote() -> None:
    settings = parse_settings(
        {
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "TEST_OPENAI_KEY",  # pragma: allowlist secret
        }  # pragma: allowlist secret
    )
    with pytest.raises(ConfigError, match="allow_remote"):
        OpenAICompatibleProvider(settings, environ=HOSTED_ENV)


def test_a_remote_backend_needs_a_key_variable_that_is_set() -> None:
    with pytest.raises(ConfigError, match="api_key_env"):
        _hosted(api_key_env=None)  # pragma: allowlist secret
    with pytest.raises(ConfigError, match="TEST_OPENAI_KEY"):
        OpenAICompatibleProvider(
            ProviderSettings.model_validate(
                {
                    "provider": "openai_compatible",
                    "model": "m",
                    "allow_remote": True,
                    "api_key_env": "TEST_OPENAI_KEY",  # pragma: allowlist secret
                    "input_usd_per_mtok": 1,
                    "output_usd_per_mtok": 1,
                }
            ),
            environ={},
        )


def test_a_remote_backend_without_a_cost_is_refused_so_the_budget_cannot_be_blind() -> None:
    with pytest.raises(ConfigError, match="input_usd_per_mtok"):
        _hosted(input_usd_per_mtok=None, output_usd_per_mtok=None)


def test_capabilities_for_hosted_and_loopback() -> None:
    hosted = _hosted().capabilities
    assert (hosted.local, hosted.strict_schema) == (False, True)
    assert (hosted.cost_per_mtok.input, hosted.cost_per_mtok.output) == (0.10, 0.50)
    local = _local().capabilities
    assert (local.local, local.strict_schema) == (True, False)
    assert local.cost_per_mtok.input == 0


def test_the_factory_builds_the_adapter() -> None:
    settings = parse_settings(
        {"provider": "openai_compatible", "model": "m", "base_url": NOTHING_LISTENING}
    )
    assert isinstance(get_provider(settings), OpenAICompatibleProvider)


def test_a_good_reply_is_parsed_with_its_usage() -> None:
    result = read_completion(_completion(), Answer, context_tokens=8192, secrets=[KEY])
    assert result.parsed == Answer(text="hi", count=1)
    assert (result.usage.input_tokens, result.usage.output_tokens) == (40, 9)


def test_a_reply_that_fails_the_schema_is_a_schema_violation_without_the_output() -> None:
    with pytest.raises(SchemaViolation) as caught:
        read_completion(_completion('{"text": 5}'), Answer, context_tokens=8192, secrets=[])
    assert "text" in caught.value.detail
    assert "5" not in caught.value.detail


def test_output_cut_off_by_the_cap_is_a_schema_violation() -> None:
    body = _completion('{"text": "hi')
    body["choices"][0]["finish_reason"] = "length"
    with pytest.raises(SchemaViolation, match="cut off"):
        read_completion(body, Answer, context_tokens=8192, secrets=[])


def test_a_refusal_field_is_the_typed_refusal() -> None:
    body = _completion(None)
    body["choices"][0]["message"]["refusal"] = "I can't help with that"
    with pytest.raises(Refusal):
        read_completion(body, Answer, context_tokens=8192, secrets=[])


def test_a_content_filter_finish_is_a_refusal() -> None:
    body = _completion("")
    body["choices"][0]["finish_reason"] = "content_filter"
    with pytest.raises(Refusal):
        read_completion(body, Answer, context_tokens=8192, secrets=[])


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": ["x"]},
        {"choices": [{"message": {"content": 5}}]},
        _completion(usage={"prompt_tokens": "many", "completion_tokens": 1}),
        _completion(usage={"prompt_tokens": 1}),
        _completion(usage=None),
        _completion(usage={"prompt_tokens": -1, "completion_tokens": 1}),
        _completion(usage={"prompt_tokens": True, "completion_tokens": 1}),
    ],
)
def test_malformed_replies_are_provider_unavailable(body: dict[str, Any]) -> None:
    with pytest.raises(ProviderUnavailable):
        read_completion(body, Answer, context_tokens=8192, secrets=[])


def test_a_prompt_count_that_fills_the_window_is_a_truncation_signal() -> None:
    body = _completion(usage={"prompt_tokens": 2048, "completion_tokens": 5})
    with pytest.raises(ContextTruncated) as caught:
        read_completion(body, Answer, context_tokens=2048, secrets=[])
    assert caught.value.input_tokens == 2048


def test_a_prompt_count_below_the_window_is_accepted() -> None:
    body = _completion(usage={"prompt_tokens": 2047, "completion_tokens": 5})
    assert read_completion(body, Answer, context_tokens=2048, secrets=[]).usage.input_tokens == 2047


def _response(status: int, text: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, text=text, headers=headers)


def test_status_429_is_rate_limited_with_retry_after() -> None:
    with pytest.raises(RateLimited) as caught:
        check_response_status(_response(429, headers={"retry-after": "7"}), 600, 2048, [KEY])
    assert caught.value.retry_after_seconds == 7.0
    with pytest.raises(RateLimited) as caught:
        check_response_status(_response(429, headers={"retry-after": "soon"}), 600, 2048, [KEY])
    assert caught.value.retry_after_seconds is None


@pytest.mark.parametrize(
    "text",
    [
        '{"error": {"code": "context_length_exceeded", "message": "too long"}}',
        '{"error": {"message": "This model\'s maximum context length is 4096 tokens"}}',
        '{"error": "Trying to keep the first 5000 tokens when context the overflows"}',
    ],
)
def test_a_400_about_context_length_is_context_truncated(text: str) -> None:
    with pytest.raises(ContextTruncated) as caught:
        check_response_status(_response(400, text=text), 600, 2048, [KEY])
    assert (caught.value.input_tokens, caught.value.context_tokens) == (600, 2048)


def test_other_failures_are_provider_unavailable_and_scrub_the_key() -> None:
    with pytest.raises(ProviderUnavailable) as caught:
        check_response_status(_response(401, text=f"bad key {KEY}" + "x" * 5000), 600, 2048, [KEY])
    assert "HTTP 401" in caught.value.reason
    assert KEY not in caught.value.reason
    assert KEY not in str(caught.value)
    assert len(caught.value.reason) < 300


def test_a_redirect_is_refused() -> None:
    with pytest.raises(ProviderUnavailable, match="HTTP 302"):
        check_response_status(
            _response(302, headers={"location": "http://evil.example/"}), 600, 2048, []
        )


def test_an_unreachable_server_error_never_contains_the_key() -> None:
    provider = _hosted(base_url=NOTHING_LISTENING)
    with pytest.raises(ProviderUnavailable) as caught:
        provider.complete_structured("s", "d", Answer, 10)
    assert caught.value.request_attempted is True
    assert KEY not in str(caught.value)
