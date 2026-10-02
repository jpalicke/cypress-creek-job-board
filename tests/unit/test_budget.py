# ABOUTME: Tests the budget limits, tracker, dry run and settings: caps checked, usage recorded.
# ABOUTME: Local backends cost no dollars but still honour the token and request caps.
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from cypress_creek.config import parse_settings
from cypress_creek.providers import BudgetExceeded, CostPerMtok, OllamaProvider, Usage
from cypress_creek.providers.base import estimate_input_tokens
from cypress_creek.providers.budget import (
    Budget,
    BudgetTracker,
    PlannedCall,
    budget_from_settings,
    dry_run_estimate,
)

FREE = CostPerMtok(input=0, output=0)
PAID = CostPerMtok(input=3.0, output=15.0)


class Answer(BaseModel):
    text: str


def _tracker(cost: CostPerMtok = FREE, **limits: Any) -> BudgetTracker:
    return BudgetTracker(Budget(**limits), cost)


def test_a_run_over_the_cap_raises_before_any_call() -> None:
    tracker = _tracker(max_input_tokens=1000)
    with pytest.raises(BudgetExceeded) as caught:
        tracker.check_before(input_tokens=1001, max_output_tokens=10)
    assert caught.value.limit_name == "input_tokens"
    assert caught.value.limit == 1000
    assert caught.value.would_reach == 1001


def test_exactly_the_cap_is_allowed() -> None:
    _tracker(max_input_tokens=1000).check_before(input_tokens=1000, max_output_tokens=10)


def test_recorded_usage_counts_toward_the_next_check() -> None:
    tracker = _tracker(max_input_tokens=1000)
    tracker.check_before(input_tokens=600, max_output_tokens=10)
    tracker.record(Usage(input_tokens=600, output_tokens=5))
    with pytest.raises(BudgetExceeded) as caught:
        tracker.check_before(input_tokens=401, max_output_tokens=10)
    assert caught.value.would_reach == 1001


def test_the_output_cap_is_checked_against_the_worst_case() -> None:
    tracker = _tracker(max_output_tokens=500)
    tracker.record(Usage(input_tokens=1, output_tokens=300))
    with pytest.raises(BudgetExceeded) as caught:
        tracker.check_before(input_tokens=1, max_output_tokens=201)
    assert caught.value.limit_name == "output_tokens"
    assert caught.value.would_reach == 501


def test_the_request_count_is_capped() -> None:
    tracker = _tracker(max_requests=2)
    for _ in range(2):
        tracker.check_before(input_tokens=1, max_output_tokens=1)
        tracker.record(Usage(input_tokens=1, output_tokens=1))
    with pytest.raises(BudgetExceeded) as caught:
        tracker.check_before(input_tokens=1, max_output_tokens=1)
    assert caught.value.limit_name == "requests"
    assert caught.value.would_reach == 3


def test_dollar_cost_comes_from_the_price_per_million_tokens() -> None:
    tracker = _tracker(PAID)
    assert tracker.cost_usd(input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(18.0)
    tracker.record(Usage(input_tokens=2_000_000, output_tokens=100_000))
    assert tracker.usd == pytest.approx(7.5)


def test_the_dollar_cap_uses_the_worst_case_output() -> None:
    tracker = _tracker(PAID, max_usd=1.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 100k input is $0.30. A 50k output cap adds up to $0.75, for $1.05 in the worst case.
    with pytest.raises(BudgetExceeded) as caught:
        tracker.check_before(input_tokens=100_000, max_output_tokens=50_000)
    assert caught.value.limit_name == "usd"
    assert caught.value.limit == 1.0
    assert caught.value.would_reach == pytest.approx(1.05)


def test_a_local_backend_costs_nothing_but_still_honours_token_caps() -> None:
    tracker = _tracker(FREE, max_usd=0.01, max_input_tokens=1000)
    tracker.record(Usage(input_tokens=900, output_tokens=900))
    assert tracker.usd == 0
    with pytest.raises(BudgetExceeded) as caught:
        tracker.check_before(input_tokens=200, max_output_tokens=10)
    assert caught.value.limit_name == "input_tokens"


def test_real_usage_above_the_estimate_blocks_the_next_call() -> None:
    tracker = _tracker(max_input_tokens=1000)
    tracker.check_before(input_tokens=100, max_output_tokens=10)
    tracker.record(Usage(input_tokens=1500, output_tokens=10))
    with pytest.raises(BudgetExceeded):
        tracker.check_before(input_tokens=1, max_output_tokens=1)


def test_the_totals_report_what_was_recorded() -> None:
    tracker = _tracker(PAID)
    tracker.record(Usage(input_tokens=10, output_tokens=4))
    tracker.record(Usage(input_tokens=5, output_tokens=1))
    assert (tracker.input_tokens, tracker.output_tokens, tracker.requests) == (15, 5, 2)


def test_the_defaults_are_conservative_and_documented() -> None:
    budget = Budget()
    assert budget.max_input_tokens == 500_000
    assert budget.max_output_tokens == 100_000
    assert budget.max_requests == 500
    assert budget.max_usd == 2.0


@pytest.mark.parametrize(
    "bad",
    [
        {"max_input_tokens": 0},
        {"max_output_tokens": -1},
        {"max_requests": 0},
        {"max_usd": 0},
        {"surprise": 1},
    ],
)
def test_bad_limits_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Budget(**bad)


def _plan(data: str = "data", cap: int = 100) -> PlannedCall:
    return PlannedCall(system="sys", data_block=data, output_schema=Answer, max_output_tokens=cap)


def test_a_dry_run_totals_the_plan_with_the_worst_case_output() -> None:
    provider = OllamaProvider(parse_settings({"provider": "ollama", "model": "m"}))
    plan = [_plan("a" * 300), _plan("b" * 300)]
    estimate = dry_run_estimate(provider, Budget(), plan)
    per_call = estimate_input_tokens(provider, "sys", "a" * 300, Answer)
    assert estimate.requests == 2
    assert estimate.input_tokens == 2 * per_call
    assert estimate.output_tokens == 200
    assert estimate.usd == 0


def test_a_plan_that_cannot_fit_the_budget_raises_before_any_call() -> None:
    provider = OllamaProvider(parse_settings({"provider": "ollama", "model": "m"}))
    with pytest.raises(BudgetExceeded) as caught:
        dry_run_estimate(provider, Budget(max_requests=1), [_plan(), _plan()])
    assert caught.value.limit_name == "requests"


def test_budget_settings_become_the_budget() -> None:
    settings = parse_settings(
        {"provider": "ollama", "model": "m", "max_input_tokens": 1234, "max_usd": 0.5}
    )
    budget = budget_from_settings(settings)
    assert budget.max_input_tokens == 1234
    assert budget.max_usd == 0.5
    assert budget.max_requests == Budget().max_requests


def test_no_budget_settings_means_the_defaults() -> None:
    settings = parse_settings({"provider": "ollama", "model": "m"})
    assert budget_from_settings(settings) == Budget()
