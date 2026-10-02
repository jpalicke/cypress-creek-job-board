# ABOUTME: Live test that BudgetedProvider records the usage a real Ollama server reports.
# ABOUTME: An unreachable server fails loudly, this test is never skipped.
import os

import httpx
import pytest
from pydantic import BaseModel

from cypress_creek.config import parse_settings
from cypress_creek.providers import BudgetExceeded, OllamaProvider
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.ollama import DEFAULT_BASE_URL

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)


class Greeting(BaseModel):
    text: str


def _budgeted(**limits: int) -> BudgetedProvider:
    settings = parse_settings(
        {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 4096}
    )
    inner = OllamaProvider(settings)
    return BudgetedProvider(
        inner, BudgetTracker(Budget(**limits), inner.capabilities.cost_per_mtok)
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
    if MODEL not in {model["name"] for model in listing["models"]}:
        pytest.fail(f"Model {MODEL} is not pulled. Run `ollama pull {MODEL}`.")


def test_the_tracker_totals_equal_the_usage_the_server_reported() -> None:
    provider = _budgeted()
    first = provider.complete_structured("Reply with a greeting.", "Say hi", Greeting, 100)
    second = provider.complete_structured("Reply with a greeting.", "Say hello", Greeting, 100)
    tracker = provider.tracker
    assert tracker.requests == 2
    assert tracker.input_tokens == first.usage.input_tokens + second.usage.input_tokens
    assert tracker.output_tokens == first.usage.output_tokens + second.usage.output_tokens
    assert tracker.usd == 0


def test_a_request_cap_stops_the_next_real_call() -> None:
    provider = _budgeted(max_requests=1)
    provider.complete_structured("Reply with a greeting.", "Say hi", Greeting, 100)
    with pytest.raises(BudgetExceeded) as caught:
        provider.complete_structured("Reply with a greeting.", "Say hi", Greeting, 100)
    assert caught.value.limit_name == "requests"
    assert provider.tracker.requests == 1
