# ABOUTME: Live test of the openai_compatible adapter against the real OpenAI API.
# ABOUTME: Run locally with a key. A missing key fails loudly, the test is never skipped.
import os

import pytest
from pydantic import BaseModel

from cypress_creek.config import parse_settings
from cypress_creek.providers import OpenAICompatibleProvider

pytestmark = [pytest.mark.live_openai, pytest.mark.needs_network]

KEY_ENV = "OPENAI_API_KEY"
MODEL = os.environ.get("CYPRESS_CREEK_OPENAI_MODEL", "gpt-6-luna")


class Greeting(BaseModel):
    text: str


def test_one_real_structured_call_returns_a_conforming_object_and_usage() -> None:
    if not os.environ.get(KEY_ENV):
        pytest.fail(f"Set {KEY_ENV} in the environment or a gitignored .env to run this test.")
    settings = parse_settings(
        {
            "provider": "openai_compatible",
            "model": MODEL,
            "allow_remote": True,
            "api_key_env": KEY_ENV,  # pragma: allowlist secret
            "context_tokens": 32768,
            "input_usd_per_mtok": 0.10,
            "output_usd_per_mtok": 0.50,
        }
    )
    provider = OpenAICompatibleProvider(settings)
    assert provider.capabilities.local is False
    result = provider.complete_structured(
        "Reply with a short greeting as JSON.", "Say hi", Greeting, max_output_tokens=200
    )
    assert result.parsed.text
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
