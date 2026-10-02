# ABOUTME: Tests the Ollama truncation guard without a server: pre-flight and post-flight rules.
# ABOUTME: The adapter must refuse an oversized prompt before it opens any connection.
import httpx
import pytest
from pydantic import BaseModel

from cypress_creek.config import ConfigError, parse_settings
from cypress_creek.providers import (
    ContextTruncated,
    ProviderUnavailable,
    RateLimited,
    get_provider,
)
from cypress_creek.providers.ollama import (
    CHARS_PER_TOKEN,
    MIN_NUM_CTX,
    OllamaProvider,
    check_post_flight,
    check_pre_flight,
    check_response_status,
    estimate_tokens,
    response_object,
    usage_count,
)

# Nothing listens on the discard port. A call that reached the network would be ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"


class Answer(BaseModel):
    text: str


def _provider(num_ctx: int = 2048, chars_per_token: int = CHARS_PER_TOKEN) -> OllamaProvider:
    settings = parse_settings(
        {
            "provider": "ollama",
            "model": "qwen3.5:0.8b",
            "base_url": NOTHING_LISTENING,
            "context_tokens": num_ctx,
        }
    )
    return OllamaProvider(settings, chars_per_token=chars_per_token)


def test_the_estimate_rounds_up_at_the_documented_ratio() -> None:
    assert CHARS_PER_TOKEN == 3
    assert estimate_tokens("", 3) == 0
    assert estimate_tokens("a" * 30, 3) == 10
    assert estimate_tokens("a" * 31, 3) == 11
    assert _provider().count_tokens_estimate("a" * 90) == 30


def test_pre_flight_allows_exactly_a_full_window() -> None:
    check_pre_flight(input_tokens=600, max_output_tokens=400, num_ctx=1000)


def test_pre_flight_refuses_one_token_over() -> None:
    with pytest.raises(ContextTruncated) as caught:
        check_pre_flight(input_tokens=601, max_output_tokens=400, num_ctx=1000)
    assert caught.value.input_tokens == 1001
    assert caught.value.context_tokens == 1000


def test_post_flight_flags_a_count_at_the_window_when_the_estimate_was_lower() -> None:
    with pytest.raises(ContextTruncated) as caught:
        check_post_flight(reported_tokens=1000, estimated_tokens=300, num_ctx=1000)
    assert caught.value.input_tokens == 1000
    assert caught.value.context_tokens == 1000


def test_post_flight_flags_a_count_near_the_window() -> None:
    with pytest.raises(ContextTruncated):
        check_post_flight(reported_tokens=950, estimated_tokens=300, num_ctx=1000)


def test_post_flight_accepts_a_count_below_the_near_full_line() -> None:
    check_post_flight(reported_tokens=949, estimated_tokens=300, num_ctx=1000)


def test_post_flight_accepts_a_full_count_the_estimate_already_predicted() -> None:
    check_post_flight(reported_tokens=960, estimated_tokens=955, num_ctx=1000)


@pytest.mark.parametrize(("num_ctx", "reported"), [(2048, 1026), (4096, 2050), (2048, 1040)])
def test_post_flight_flags_the_half_window_count_a_truncating_server_reports(
    num_ctx: int, reported: int
) -> None:
    with pytest.raises(ContextTruncated):
        check_post_flight(reported_tokens=reported, estimated_tokens=30, num_ctx=num_ctx)


@pytest.mark.parametrize("reported", [1023, 1041])
def test_post_flight_accepts_counts_just_outside_the_half_window_band(reported: int) -> None:
    check_post_flight(reported_tokens=reported, estimated_tokens=30, num_ctx=2048)


def test_post_flight_accepts_a_half_window_count_the_estimate_bounded() -> None:
    check_post_flight(reported_tokens=1026, estimated_tokens=1100, num_ctx=2048)


def test_an_oversized_prompt_is_refused_before_any_connection() -> None:
    provider = _provider(num_ctx=2048)
    with pytest.raises(ContextTruncated) as caught:
        provider.complete_structured("s" * 300, "d" * 7000, Answer, max_output_tokens=200)
    assert caught.value.context_tokens == 2048
    assert caught.value.input_tokens > 2048


def test_a_window_below_the_server_floor_is_a_config_error() -> None:
    assert MIN_NUM_CTX == 2048
    with pytest.raises(ConfigError, match="context_tokens"):
        _provider(num_ctx=2047)


def test_the_schema_counts_toward_the_estimate() -> None:
    class Heavy(BaseModel):
        text: str = "x" * 7000

    provider = _provider(num_ctx=2048)
    with pytest.raises(ContextTruncated):
        provider.complete_structured("s", "d", Heavy, max_output_tokens=10)


def test_the_output_cap_counts_toward_the_estimate() -> None:
    provider = _provider(num_ctx=2048)
    with pytest.raises(ContextTruncated):
        provider.complete_structured("s", "d", Answer, max_output_tokens=2048)


def test_capabilities_report_the_configured_window() -> None:
    capabilities = _provider(num_ctx=4096).capabilities
    assert capabilities.context_tokens == 4096
    assert capabilities.local is True
    assert capabilities.strict_schema is True
    assert capabilities.cost_per_mtok.input == 0
    assert capabilities.cost_per_mtok.output == 0


def test_the_factory_builds_the_ollama_adapter() -> None:
    settings = parse_settings({"provider": "ollama", "model": "qwen3.5:0.8b"})
    assert isinstance(get_provider(settings), OllamaProvider)


def _response(status: int, text: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, text=text, headers=headers)


def test_status_429_is_rate_limited_with_the_retry_after_value() -> None:
    with pytest.raises(RateLimited) as caught:
        check_response_status(_response(429, headers={"retry-after": "7"}))
    assert caught.value.retry_after_seconds == 7.0


@pytest.mark.parametrize("headers", [{}, {"retry-after": "soon"}])
def test_status_429_without_a_usable_retry_after_has_none(headers: dict[str, str]) -> None:
    with pytest.raises(RateLimited) as caught:
        check_response_status(_response(429, headers=headers))
    assert caught.value.retry_after_seconds is None


def test_other_failures_are_provider_unavailable_with_a_bounded_body() -> None:
    with pytest.raises(ProviderUnavailable) as caught:
        check_response_status(_response(500, text="x" * 5000))
    assert "HTTP 500" in caught.value.reason
    assert len(caught.value.reason) < 300


def test_a_redirect_is_refused_not_followed() -> None:
    with pytest.raises(ProviderUnavailable, match="HTTP 302"):
        check_response_status(_response(302, headers={"location": "http://evil.example/"}))


def test_a_200_passes_the_status_check() -> None:
    check_response_status(_response(200))


def test_a_json_object_body_is_returned() -> None:
    assert response_object(_response(200, text='{"a": 1}')) == {"a": 1}


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '"text"'])
def test_a_body_that_is_not_a_json_object_is_provider_unavailable(text: str) -> None:
    with pytest.raises(ProviderUnavailable):
        response_object(_response(200, text=text))


def test_usage_counts_must_be_present_non_negative_integers() -> None:
    assert usage_count({"eval_count": 12}, "eval_count") == 12
    for bad in ({}, {"eval_count": -1}, {"eval_count": True}, {"eval_count": "12"}):
        with pytest.raises(ProviderUnavailable, match="eval_count"):
            usage_count(bad, "eval_count")
