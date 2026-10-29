# ABOUTME: Live test that draft help works against a real Ollama server and model.
# ABOUTME: An unreachable server fails loudly, and the draft always carries its validator verdicts.
import os

import httpx
import pytest
import yaml

from cypress_creek.config import parse_settings
from cypress_creek.facts.loader import parse_bank
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind
from cypress_creek.pipeline.draft import DraftStatus, draft, render_draft
from cypress_creek.pipeline.retrieve import RequirementCandidates
from cypress_creek.providers import OllamaProvider
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


def test_a_real_model_drafts_and_every_sentence_carries_validator_verdicts() -> None:
    bank = parse_bank(yaml.safe_load(BANK))
    provider = OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 8192}
        )
    )
    candidates = RequirementCandidates(
        requirement_id="R-1",
        fact_ids=["F-0001"],
        dropped_count=0,
        support=Support.STRONG,
        gate=Gate.TERM_MATCH,
    )
    result = draft(REQUIREMENT, candidates, bank, provider)
    assert result.needs_human_review is True
    assert result.status in (DraftStatus.DRAFTED, DraftStatus.NOT_RUN)
    for sentence in result.sentences:
        assert {v.validator for v in sentence.verdicts} >= {"V4", "V5", "V9"}
    assert "human review" in render_draft(result).lower()
