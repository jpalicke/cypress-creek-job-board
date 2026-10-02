# ABOUTME: Tests the shared retry policy: which typed errors are retried and how often.
# ABOUTME: The sleeper is a plain recording function, so no test waits on a real clock.
from collections.abc import Callable

import pytest

from cypress_creek.providers.errors import (
    BudgetExceeded,
    ContextTruncated,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
)
from cypress_creek.providers.retry import RetryPolicy, call_with_retry


class Script:
    """Raises the given errors in order, then returns "done". Records each call's feedback."""

    def __init__(self, *errors: ProviderError) -> None:
        self.errors = list(errors)
        self.feedback: list[str | None] = []

    def __call__(self, feedback: str | None) -> str:
        self.feedback.append(feedback)
        if self.errors:
            raise self.errors.pop(0)
        return "done"


def _sleeper() -> tuple[list[float], Callable[[float], None]]:
    slept: list[float] = []
    return slept, slept.append


def test_a_success_is_returned_without_retrying() -> None:
    slept, sleep = _sleeper()
    script = Script()
    assert call_with_retry(script, sleep=sleep) == "done"
    assert script.feedback == [None]
    assert slept == []


def test_a_schema_violation_is_retried_once_with_only_the_schema_error() -> None:
    script = Script(SchemaViolation(schema_name="Answer", detail="verdict: field required"))
    assert call_with_retry(script, sleep=_sleeper()[1]) == "done"
    assert script.feedback == [None, "verdict: field required"]


def test_a_second_schema_violation_is_raised() -> None:
    violation = SchemaViolation(schema_name="Answer", detail="bad")
    script = Script(violation, violation)
    with pytest.raises(SchemaViolation):
        call_with_retry(script, sleep=_sleeper()[1])
    assert len(script.feedback) == 2


@pytest.mark.parametrize(
    "error",
    [
        ContextTruncated(input_tokens=2, context_tokens=1),
        BudgetExceeded(limit_name="usd", limit=1.0, would_reach=2.0),
        Refusal(provider="p"),
        ProviderUnavailable(provider="p", reason="down"),
    ],
    ids=["context", "budget", "refusal", "unavailable"],
)
def test_other_errors_are_never_retried(error: ProviderError) -> None:
    script = Script(error)
    with pytest.raises(type(error)):
        call_with_retry(script, sleep=_sleeper()[1])
    assert len(script.feedback) == 1


def test_rate_limits_back_off_exponentially_up_to_the_cap() -> None:
    slept, sleep = _sleeper()
    script = Script(RateLimited(), RateLimited(), RateLimited())
    policy = RetryPolicy(max_rate_limit_retries=3, base_delay_seconds=1.0, max_delay_seconds=3.0)
    assert call_with_retry(script, sleep=sleep, policy=policy) == "done"
    assert slept == [1.0, 2.0, 3.0]


def test_a_retry_after_hint_is_used_but_capped() -> None:
    slept, sleep = _sleeper()
    script = Script(RateLimited(retry_after_seconds=0.5), RateLimited(retry_after_seconds=999))
    policy = RetryPolicy(max_rate_limit_retries=3, base_delay_seconds=1.0, max_delay_seconds=10.0)
    call_with_retry(script, sleep=sleep, policy=policy)
    assert slept == [0.5, 10.0]


def test_rate_limits_are_bounded() -> None:
    slept, sleep = _sleeper()
    script = Script(*[RateLimited() for _ in range(5)])
    policy = RetryPolicy(max_rate_limit_retries=2)
    with pytest.raises(RateLimited):
        call_with_retry(script, sleep=sleep, policy=policy)
    assert len(script.feedback) == 3
    assert len(slept) == 2


def test_schema_retries_and_rate_limit_retries_are_counted_separately() -> None:
    script = Script(RateLimited(), SchemaViolation(schema_name="A", detail="d"), RateLimited())
    assert call_with_retry(script, sleep=_sleeper()[1]) == "done"
    assert script.feedback == [None, None, "d", "d"]


def test_the_policy_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_rate_limit_retries=-1)
    with pytest.raises(ValueError):
        RetryPolicy(base_delay_seconds=0)
