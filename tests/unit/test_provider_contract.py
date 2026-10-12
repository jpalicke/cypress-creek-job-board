# ABOUTME: Tests the provider contract types and the six typed errors every backend raises.
# ABOUTME: Errors are branched on by class and must never carry a secret in any message or field.
import pytest
from pydantic import BaseModel, ValidationError

from cypress_creek.providers.base import Capabilities, CostPerMtok, StructuredResult, Usage
from cypress_creek.providers.errors import (
    BudgetExceeded,
    ContextTruncated,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
)

KEY = "sk-test-SECRET-1234567890"


class Answer(BaseModel):
    verdict: str


def test_every_error_is_a_provider_error_and_a_distinct_class() -> None:
    classes = [
        ContextTruncated,
        SchemaViolation,
        ProviderUnavailable,
        RateLimited,
        BudgetExceeded,
        Refusal,
    ]
    assert all(issubclass(cls, ProviderError) for cls in classes)
    assert len(set(classes)) == 6
    for cls in classes:
        others = [other for other in classes if other is not cls]
        assert not any(issubclass(cls, other) for other in others)


def test_context_truncated_carries_the_token_counts() -> None:
    error = ContextTruncated(input_tokens=9000, context_tokens=8192)
    assert (error.input_tokens, error.context_tokens) == (9000, 8192)
    assert str(error) == "input of 9000 tokens exceeds context of 8192"


def test_reported_truncation_does_not_claim_the_reported_count_exceeds_context() -> None:
    error = ContextTruncated(input_tokens=16386, context_tokens=32768, detected_after_call=True)
    assert (error.input_tokens, error.context_tokens) == (16386, 32768)
    assert str(error) == (
        "server reported 16386 prompt tokens matching a truncation signature for context of 32768"
    )


def test_schema_violation_carries_the_schema_error() -> None:
    error = SchemaViolation(schema_name="Answer", detail="verdict: field required")
    assert error.schema_name == "Answer"
    assert error.detail == "verdict: field required"


def test_rate_limited_carries_the_retry_after_hint() -> None:
    assert RateLimited(retry_after_seconds=2.5).retry_after_seconds == 2.5
    assert RateLimited().retry_after_seconds is None


def test_budget_exceeded_carries_the_amounts() -> None:
    error = BudgetExceeded(limit_name="usd", limit=1.0, would_reach=1.25)
    assert (error.limit_name, error.limit, error.would_reach) == ("usd", 1.0, 1.25)
    assert "usd" in str(error)


def test_refusal_names_the_provider() -> None:
    assert Refusal(provider="anthropic").provider == "anthropic"


def test_unavailable_scrubs_the_secret_from_message_and_fields() -> None:
    error = ProviderUnavailable(provider="openai", reason=f"401 for Bearer {KEY}", secrets=[KEY])
    assert KEY not in str(error)
    assert KEY not in error.reason
    assert KEY not in repr(error)
    assert KEY not in repr(error.args)


def test_schema_violation_scrubs_the_secret_from_the_detail() -> None:
    error = SchemaViolation(schema_name="Answer", detail=f"echoed {KEY}", secrets=[KEY])
    assert KEY not in error.detail
    assert KEY not in str(error)


def test_an_empty_secret_does_not_mangle_the_text() -> None:
    error = ProviderUnavailable(provider="ollama", reason="connection refused", secrets=[""])
    assert error.reason == "connection refused"


def test_capabilities_describe_a_backend() -> None:
    caps = Capabilities(
        context_tokens=8192,
        strict_schema=True,
        local=True,
        cost_per_mtok=CostPerMtok(input=0, output=0),
    )
    assert caps.context_tokens == 8192
    assert caps.local


def test_capabilities_reject_a_non_positive_context() -> None:
    with pytest.raises(ValidationError):
        Capabilities(
            context_tokens=0,
            strict_schema=False,
            local=True,
            cost_per_mtok=CostPerMtok(input=0, output=0),
        )


def test_cost_and_usage_reject_negative_numbers() -> None:
    with pytest.raises(ValidationError):
        CostPerMtok(input=-1, output=0)
    with pytest.raises(ValidationError):
        Usage(input_tokens=-1, output_tokens=0)


def test_a_result_carries_the_parsed_model_raw_text_and_usage() -> None:
    result = StructuredResult[Answer](
        parsed=Answer(verdict="yes"),
        raw_text='{"verdict": "yes"}',
        usage=Usage(input_tokens=10, output_tokens=4),
    )
    assert result.parsed.verdict == "yes"
    assert result.usage.output_tokens == 4
