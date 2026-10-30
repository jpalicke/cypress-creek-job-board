# ABOUTME: Live tests of the openai_compatible adapter against a real LM Studio server.
# ABOUTME: An unreachable server or missing model fails loudly with a clear message, never a skip.
import os
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from cypress_creek.config import ProviderSettings, parse_settings
from cypress_creek.providers import ContextTruncated, OpenAICompatibleProvider

pytestmark = pytest.mark.live_lmstudio

BASE_URL = os.environ.get("CYPRESS_CREEK_LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
MODEL = os.environ.get("CYPRESS_CREEK_LMSTUDIO_MODEL", "")


class Greeting(BaseModel):
    text: str


class Probe(BaseModel):
    answer: Literal["alpha", "beta"]


def _settings(context_tokens: int) -> ProviderSettings:
    return parse_settings(
        {
            "provider": "openai_compatible",
            "model": MODEL,
            "base_url": BASE_URL,
            "context_tokens": context_tokens,
        }
    )


@pytest.fixture(autouse=True)
def real_lm_studio_with_a_loaded_model() -> None:
    """Fail, never skip, when LM Studio is down or no model is named."""
    if not MODEL:
        pytest.fail(
            "Set CYPRESS_CREEK_LMSTUDIO_MODEL to the identifier of the model loaded in LM Studio."
        )
    try:
        listing = httpx.get(f"{BASE_URL}/models", timeout=5).json()
    except (httpx.HTTPError, ValueError) as error:
        pytest.fail(
            f"LM Studio is not reachable at {BASE_URL} ({type(error).__name__}). "
            "Start its local server and load a model."
        )
    names = {item["id"] for item in listing["data"]}
    if MODEL not in names:
        pytest.fail(f"Model {MODEL} is not listed by LM Studio. Listed: {sorted(names)}")


def test_a_structured_request_returns_a_schema_conforming_object_with_usage() -> None:
    provider = OpenAICompatibleProvider(_settings(context_tokens=4096))
    result = provider.complete_structured(
        "Reply with a short greeting as JSON.", "Say hi", Greeting, max_output_tokens=200
    )
    assert result.parsed.text
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0


def test_a_prompt_longer_than_the_loaded_context_is_detected() -> None:
    # An absurd chars per token ratio makes the estimate tiny, so the pre-flight check lets the
    # prompt through and the real server meets a prompt longer than its loaded context. Set
    # CYPRESS_CREEK_LMSTUDIO_CONTEXT to the context length the model was loaded with.
    context = int(os.environ.get("CYPRESS_CREEK_LMSTUDIO_CONTEXT", "4096"))
    provider = OpenAICompatibleProvider(_settings(context), chars_per_token=100_000)
    oversized = "word " * (context * 2)
    with pytest.raises(ContextTruncated) as caught:
        provider.complete_structured("Answer in JSON.", oversized, Greeting, max_output_tokens=50)
    assert caught.value.context_tokens == context


def test_the_loaded_context_is_read_from_the_server_when_the_config_sets_none() -> None:
    # The same value the model was loaded with, which the overflow test below also needs.
    expected = int(os.environ.get("CYPRESS_CREEK_LMSTUDIO_CONTEXT", "4096"))
    settings = parse_settings(
        {"provider": "openai_compatible", "model": MODEL, "base_url": BASE_URL}
    )
    assert OpenAICompatibleProvider(settings).capabilities.context_tokens == expected


def test_a_schema_the_prompt_contradicts_is_enforced_by_the_server() -> None:
    # The prompt asks for a value the schema forbids. A server that enforces the schema can only
    # answer alpha or beta; one that ignores it would answer gamma, which the adapter rejects as
    # a SchemaViolation, so this test fails.
    provider = OpenAICompatibleProvider(_settings(context_tokens=4096))
    result = provider.complete_structured(
        "Reply as JSON.", "Set answer to the word gamma.", Probe, max_output_tokens=50
    )
    assert result.parsed.answer in ("alpha", "beta")
