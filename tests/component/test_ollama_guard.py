# ABOUTME: Tests the Ollama truncation guard without a server: pre-flight and post-flight rules.
# ABOUTME: The adapter must refuse an oversized prompt before it opens any connection.
import pytest
from pydantic import BaseModel

from cypress_creek.config import parse_settings
from cypress_creek.providers import ContextTruncated, get_provider
from cypress_creek.providers.ollama import (
    CHARS_PER_TOKEN,
    OllamaProvider,
    check_post_flight,
    check_pre_flight,
    estimate_tokens,
)

# Nothing listens on the discard port. A call that reached the network would be ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"


class Answer(BaseModel):
    text: str


def _provider(num_ctx: int = 1000, chars_per_token: int = CHARS_PER_TOKEN) -> OllamaProvider:
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


def test_an_oversized_prompt_is_refused_before_any_connection() -> None:
    provider = _provider(num_ctx=1000)
    with pytest.raises(ContextTruncated) as caught:
        provider.complete_structured("s" * 300, "d" * 3000, Answer, max_output_tokens=200)
    assert caught.value.context_tokens == 1000
    assert caught.value.input_tokens > 1000


def test_the_schema_counts_toward_the_estimate() -> None:
    class Heavy(BaseModel):
        text: str = "x" * 3000

    provider = _provider(num_ctx=1000)
    with pytest.raises(ContextTruncated):
        provider.complete_structured("s", "d", Heavy, max_output_tokens=10)


def test_the_output_cap_counts_toward_the_estimate() -> None:
    provider = _provider(num_ctx=1000)
    with pytest.raises(ContextTruncated):
        provider.complete_structured("s", "d", Answer, max_output_tokens=1000)


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
