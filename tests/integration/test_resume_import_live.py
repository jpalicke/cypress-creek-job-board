# ABOUTME: Live test of resume import: a real Ollama model reads the fictional resume.
# ABOUTME: Whatever it proposes, every surviving candidate must pass V15. Never skipped.
import os
from pathlib import Path

import httpx
import pytest

from cypress_creek.config import parse_settings
from cypress_creek.ingest.normalize import normalize
from cypress_creek.pipeline.resume_import import propose_candidates
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.validators.candidates import ProposedFact, check_candidate_grounded

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
RESUME = (Path(__file__).parent.parent / "fixtures" / "resume" / "fictional_resume.txt").read_text(
    encoding="utf-8"
)


@pytest.fixture(autouse=True)
def real_ollama_with_the_model() -> None:
    try:
        listing = httpx.get(f"{BASE_URL}/api/tags", timeout=5).json()
    except httpx.HTTPError as error:
        pytest.fail(f"Ollama is not reachable at {BASE_URL} ({error}). Start `ollama serve`.")
    if MODEL not in {model["name"] for model in listing["models"]}:
        pytest.fail(f"Model {MODEL} is not pulled. Run `ollama pull {MODEL}`.")


def test_every_candidate_a_real_model_leaves_standing_passes_the_validator() -> None:
    provider = OllamaProvider(
        parse_settings(
            {
                "provider": "ollama",
                "model": MODEL,
                "base_url": BASE_URL,
                "context_tokens": 8192,
                # A slow shared runner can take minutes for one call of a small model.
                "request_timeout_seconds": 900,
            }
        )
    )

    result = propose_candidates(RESUME, provider)

    assert result.status in {"done", "not_run"}, result
    text, _ = normalize(RESUME)
    for candidate in result.candidates:
        verdict = check_candidate_grounded(
            text,
            ProposedFact(claim=candidate.claim, source=candidate.source, tags=candidate.tags),
        )
        assert verdict.passed, (candidate, verdict)
        assert candidate.source in text
