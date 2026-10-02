# ABOUTME: Live test that stage 3 entailment works against a real Ollama server and model.
# ABOUTME: An unreachable server fails loudly, this test is never skipped.
import os
from pathlib import Path

import httpx
import pytest

from cypress_creek.config import parse_settings
from cypress_creek.facts import load_bank
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind
from cypress_creek.pipeline.entail import Entailment, entail
from cypress_creek.pipeline.retrieve import RequirementCandidates
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.scoring.support import Gate, Support

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
BANK = """
facts:
  - id: F-0001
    claim: Ran a fictional Python data service for 3 years.
    kind: project
    tags: [{name: python, level: expert}]
    verified_on: 2024-01-01
    evidence: {type: repo, pointer: "https://example.invalid/a"}
    share: shareable
"""
REQUIREMENT = Requirement(
    id="R-1",
    text="Needs Python.",
    span=(0, 13),
    kind=RequirementKind.SKILL,
    term="python",
    importance=Importance.REQUIRED,
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


def test_a_real_model_answers_one_call_and_the_result_never_exceeds_the_ceiling(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bank.yaml"
    path.write_text(BANK, encoding="utf8")
    bank = load_bank(path)
    settings = parse_settings(
        {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 4096}
    )
    inner = OllamaProvider(settings)
    tracker = BudgetTracker(Budget(), inner.capabilities.cost_per_mtok)
    candidates = RequirementCandidates(
        requirement_id="R-1",
        fact_ids=["F-0001"],
        dropped_count=0,
        support=Support.STRONG,
        gate=Gate.TERM_MATCH,
    )
    result = entail(REQUIREMENT, candidates, bank, BudgetedProvider(inner, tracker))
    assert tracker.requests >= 1
    assert result.entailment in {Entailment.CONFIRMED, Entailment.DOWNGRADED, Entailment.NOT_RUN}
    assert result.match.ceiling is Support.STRONG
    assert result.match.support in {Support.STRONG, Support.PARTIAL, Support.NONE}
    if result.entailment is Entailment.NOT_RUN:
        assert result.failure is not None
    else:
        assert result.usage is not None
        assert result.fact_ids == [] or result.fact_ids == ["F-0001"]
