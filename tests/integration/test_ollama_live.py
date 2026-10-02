# ABOUTME: Live tests of the Ollama adapter against a real server running the small CI model.
# ABOUTME: An unreachable server fails loudly with a clear message, these tests are never skipped.
import os

import httpx
import pytest
from pydantic import BaseModel

from cypress_creek.config import ProviderSettings, parse_settings
from cypress_creek.providers import (
    ContextTruncated,
    OllamaProvider,
    ProviderUnavailable,
    SchemaViolation,
)
from cypress_creek.providers.ollama import DEFAULT_BASE_URL

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)


class Greeting(BaseModel):
    text: str


def _settings(num_ctx: int, base_url: str = BASE_URL) -> ProviderSettings:
    return parse_settings(
        {"provider": "ollama", "model": MODEL, "base_url": base_url, "context_tokens": num_ctx}
    )


@pytest.fixture(autouse=True)
def real_ollama_with_the_model() -> None:
    """Fail, never skip, when the server or the model is missing."""
    try:
        listing = httpx.get(f"{BASE_URL}/api/tags", timeout=5).json()
    except httpx.HTTPError as error:
        pytest.fail(
            f"Ollama is not reachable at {BASE_URL} ({error}). Start it with `ollama serve`."
        )
    names = {model["name"] for model in listing["models"]}
    if MODEL not in names:
        pytest.fail(f"Model {MODEL} is not pulled. Run `ollama pull {MODEL}`.")


def test_a_prompt_longer_than_num_ctx_raises_context_truncated() -> None:
    # An absurd chars per token ratio makes the estimate tiny, so the pre-flight check lets the
    # prompt through and the real server truncates it. The post-flight check must catch that.
    provider = OllamaProvider(_settings(num_ctx=2048), chars_per_token=1000)
    oversized = "word " * 6000
    with pytest.raises(ContextTruncated) as caught:
        provider.complete_structured("Answer in JSON.", oversized, Greeting, max_output_tokens=50)
    assert caught.value.context_tokens == 2048


def test_the_conservative_estimate_refuses_the_same_prompt_before_calling() -> None:
    provider = OllamaProvider(_settings(num_ctx=2048))
    with pytest.raises(ContextTruncated):
        provider.complete_structured("Answer in JSON.", "word " * 6000, Greeting, 50)


def test_a_small_request_returns_a_parsed_object_and_usage() -> None:
    provider = OllamaProvider(_settings(num_ctx=4096))
    result = provider.complete_structured(
        "Reply with a short greeting in the text field.", "Say hi", Greeting, 100
    )
    assert isinstance(result.parsed, Greeting)
    assert result.parsed.text
    assert result.raw_text
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0


def test_a_server_that_is_not_there_is_provider_unavailable() -> None:
    provider = OllamaProvider(_settings(num_ctx=4096, base_url="http://127.0.0.1:9"))
    with pytest.raises(ProviderUnavailable):
        provider.complete_structured("Answer in JSON.", "Say hi", Greeting, 50)


def test_an_unknown_model_is_provider_unavailable_with_the_server_status() -> None:
    settings = parse_settings(
        {"provider": "ollama", "model": "no-such-model:1b", "base_url": BASE_URL}
    )
    with pytest.raises(ProviderUnavailable, match="HTTP 404"):
        OllamaProvider(settings).complete_structured("Answer in JSON.", "Say hi", Greeting, 50)


def test_output_cut_off_by_the_cap_is_a_schema_violation_without_the_output() -> None:
    provider = OllamaProvider(_settings(num_ctx=4096))
    with pytest.raises(SchemaViolation) as caught:
        provider.complete_structured("Reply with a long greeting.", "Say hi", Greeting, 3)
    assert caught.value.schema_name == "Greeting"
    assert "{" not in caught.value.detail
