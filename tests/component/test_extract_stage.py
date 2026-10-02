# ABOUTME: Tests the extraction stage around a real Ollama adapter that cannot answer.
# ABOUTME: Each typed provider failure ends as an incomplete result, never as invented requirements.
import json
from pathlib import Path

import pytest

from cypress_creek.config import parse_settings
from cypress_creek.pipeline.extract import (
    ExtractionResult,
    ExtractionStatus,
    extract_requirements,
    failure_label,
    finish_extraction,
)
from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.providers import (
    BudgetExceeded,
    ContextTruncated,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
    Usage,
)
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.ollama import OllamaProvider

FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"
POSTING = (FIXTURES / "posting.txt").read_text(encoding="utf-8")
RECORDED = json.loads((FIXTURES / "recorded_qwen3.5-0.8b.json").read_text(encoding="utf-8"))

# Nothing listens on the discard port. A call that reached the network is ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"


def _provider() -> OllamaProvider:
    settings = parse_settings(
        {"provider": "ollama", "model": "qwen3.5:0.8b", "base_url": NOTHING_LISTENING}
    )
    return OllamaProvider(settings)


def _no_sleep(_seconds: float) -> None:
    raise AssertionError("nothing in these tests should wait")


def test_an_unreachable_backend_gives_an_incomplete_result_with_no_requirements() -> None:
    result = extract_requirements(POSTING, _provider(), sleep=_no_sleep)
    assert result.status is ExtractionStatus.INCOMPLETE
    assert result.failure == "provider_unavailable"
    assert result.requirements == []
    assert result.usage is None
    assert len(result.prompt_hash) == 64


def test_a_posting_that_cannot_fit_the_context_gives_an_incomplete_result() -> None:
    result = extract_requirements("Needs Python. " * 3000, _provider(), sleep=_no_sleep)
    assert result.status is ExtractionStatus.INCOMPLETE
    assert result.failure == "context_truncated"


def test_a_budget_stop_is_not_swallowed() -> None:
    inner = _provider()
    tracker = BudgetTracker(Budget(max_input_tokens=10), inner.capabilities.cost_per_mtok)
    with pytest.raises(BudgetExceeded):
        extract_requirements(POSTING, BudgetedProvider(inner, tracker), sleep=_no_sleep)
    assert tracker.requests == 0


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (SchemaViolation("ExtractionOutput", "bad"), "schema_violation"),
        (ContextTruncated(5000, 4096), "context_truncated"),
        (ProviderUnavailable("ollama", "down"), "provider_unavailable"),
        (RateLimited(), "rate_limited"),
        (Refusal("ollama"), "refusal"),
    ],
)
def test_each_typed_provider_failure_has_its_own_label(error: ProviderError, label: str) -> None:
    assert failure_label(error) == label


def test_a_budget_error_has_no_label_because_it_is_never_a_result() -> None:
    assert failure_label(BudgetExceeded("usd", 1, 2)) is None


def test_a_parsed_answer_becomes_an_ok_result_with_usage_and_hash() -> None:
    output = ExtractionOutput.model_validate(RECORDED)
    result = finish_extraction(POSTING, output, "a" * 64, Usage(input_tokens=300, output_tokens=80))
    assert result.status is ExtractionStatus.OK
    assert result.failure is None
    assert [r.id for r in result.requirements] == ["R-1", "R-2"]
    assert result.usage == Usage(input_tokens=300, output_tokens=80)
    assert result.prompt_hash == "a" * 64
    assert result.schema_version == 1


def test_the_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        ExtractionResult.model_validate(
            {
                "status": "incomplete",
                "requirements": [],
                "dropped": [],
                "not_assessed_count": 0,
                "failure": "refusal",
                "usage": None,
                "prompt_hash": "a" * 64,
                "schema_version": 1,
                "obey": "me",
            }
        )
