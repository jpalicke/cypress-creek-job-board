# ABOUTME: Tests BudgetedProvider around a real Ollama adapter that has no server to talk to.
# ABOUTME: Proves the budget is checked before any connection and failed calls are not recorded.
import json

import pytest
from pydantic import BaseModel

from cypress_creek.config import parse_settings
from cypress_creek.providers import BudgetExceeded, ProviderUnavailable
from cypress_creek.providers.base import estimate_input_tokens
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.ollama import OllamaProvider

# Nothing listens on the discard port. A call that reached the network is ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"


class Answer(BaseModel):
    text: str


def _inner() -> OllamaProvider:
    settings = parse_settings(
        {"provider": "ollama", "model": "qwen3.5:0.8b", "base_url": NOTHING_LISTENING}
    )
    return OllamaProvider(settings)


def _wrapped(**limits: int) -> tuple[BudgetedProvider, BudgetTracker]:
    inner = _inner()
    tracker = BudgetTracker(Budget(**limits), inner.capabilities.cost_per_mtok)
    return BudgetedProvider(inner, tracker), tracker


def test_the_estimate_counts_system_data_and_schema_text() -> None:
    inner = _inner()
    schema_text = json.dumps(Answer.model_json_schema())
    expected = sum(inner.count_tokens_estimate(t) for t in ("sys", "data", schema_text))
    assert estimate_input_tokens(inner, "sys", "data", Answer) == expected


def test_a_call_over_the_budget_is_refused_before_any_connection() -> None:
    provider, tracker = _wrapped(max_input_tokens=10)
    with pytest.raises(BudgetExceeded) as caught:
        provider.complete_structured("system text", "data " * 100, Answer, max_output_tokens=10)
    assert caught.value.limit_name == "input_tokens"
    assert tracker.requests == 0


def test_a_call_inside_the_budget_reaches_the_inner_provider() -> None:
    provider, tracker = _wrapped()
    with pytest.raises(ProviderUnavailable):
        provider.complete_structured("system text", "data", Answer, max_output_tokens=10)
    assert tracker.requests == 0


def test_the_wrapper_reports_the_inner_capabilities_and_estimate() -> None:
    provider, _ = _wrapped()
    inner = _inner()
    assert provider.capabilities == inner.capabilities
    assert provider.count_tokens_estimate("a" * 30) == inner.count_tokens_estimate("a" * 30)
