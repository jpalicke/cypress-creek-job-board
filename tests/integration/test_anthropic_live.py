# ABOUTME: Live test of the Anthropic adapter against the real Messages API with a key from the env.
# ABOUTME: A missing key or an unreachable API fails loudly, this test is never skipped or faked.
import os

import pytest
from pydantic import BaseModel

from cypress_creek.config import parse_settings
from cypress_creek.providers import AnthropicProvider, ProviderUnavailable

pytestmark = [pytest.mark.live, pytest.mark.needs_network]

KEY_ENV = "ANTHROPIC_API_KEY"
WRONG_ENV = "ANTHROPIC_WRONG_VALUE"  # pragma: allowlist secret
MODEL = os.environ.get("CYPRESS_CREEK_LIVE_ANTHROPIC_MODEL", "claude-sonnet-5-5")


class Greeting(BaseModel):
    text: str
    word_count: int


@pytest.fixture
def a_real_key() -> None:
    """Fail, never skip, when there is no key to call the real API with."""
    if not os.environ.get(KEY_ENV):
        pytest.fail(
            f"{KEY_ENV} is not set. Export a real Anthropic API key, or put it in a gitignored "
            f".env and load it into the shell, then run this test again."
        )


def _provider() -> AnthropicProvider:
    settings = parse_settings(
        {"provider": "anthropic", "model": MODEL, "allow_remote": True, "api_key_env": KEY_ENV}
    )
    return AnthropicProvider(settings)


def test_one_real_structured_call_returns_a_conforming_object_and_real_usage(
    a_real_key: None,
) -> None:
    result = _provider().complete_structured(
        "Reply with a short greeting and count its words.",
        "<<<POSTING live>>>\nSay hello.\n<<<END POSTING live>>>",
        Greeting,
        max_output_tokens=2000,
    )
    assert isinstance(result.parsed, Greeting)
    assert result.parsed.text
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0


def test_a_wrong_key_is_unavailable_and_never_echoed() -> None:
    bad = "sk-ant-invalid-0000000000000000"  # pragma: allowlist secret
    settings = parse_settings(
        {"provider": "anthropic", "model": MODEL, "allow_remote": True, "api_key_env": WRONG_ENV}
    )
    provider = AnthropicProvider(settings, environ={WRONG_ENV: bad})
    with pytest.raises(ProviderUnavailable, match="HTTP 401") as caught:
        provider.complete_structured("s", "d", Greeting, max_output_tokens=50)
    assert bad not in str(caught.value)
