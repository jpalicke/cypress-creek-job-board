# ABOUTME: Live test that stage 1 extraction works against a real Ollama server and model.
# ABOUTME: An unreachable server fails loudly, this test is never skipped.
import os
from pathlib import Path

import httpx
import pytest

from cypress_creek.config import parse_settings
from cypress_creek.pipeline.extract import ExtractionStatus, extract_requirements
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.validators.extraction import check_importance, check_verbatim_span
from cypress_creek.validators.requirements import check_requirement_cap

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
POSTING = (Path(__file__).parent.parent / "fixtures" / "extraction" / "posting.txt").read_text(
    encoding="utf-8"
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


def test_a_real_model_extracts_requirements_that_pass_the_validators() -> None:
    settings = parse_settings(
        {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 4096}
    )
    inner = OllamaProvider(settings)
    tracker = BudgetTracker(Budget(), inner.capabilities.cost_per_mtok)
    result = extract_requirements(POSTING, BudgetedProvider(inner, tracker))
    assert result.status is ExtractionStatus.OK, result.failure
    assert result.requirements, "the model found nothing in a posting that lists requirements"
    for requirement in result.requirements:
        assert POSTING[slice(*requirement.span)] == requirement.text
        assert check_verbatim_span(POSTING, requirement).passed
        assert check_importance(POSTING, requirement).passed
    assert check_requirement_cap(result.requirements).passed
    assert result.usage is not None
    assert result.usage.input_tokens == tracker.input_tokens
    assert tracker.requests == 1
