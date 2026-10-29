# ABOUTME: Live test that a real Ollama proposes company names that then pass through the filter.
# ABOUTME: An unreachable server fails loudly, this test is never skipped. Quality is not judged.
import os
from pathlib import Path

import httpx
import pytest

from cypress_creek.config import parse_settings
from cypress_creek.discovery.profile import tag_profile
from cypress_creek.discovery.suggestions import NameOutcome, filter_names, propose_names
from cypress_creek.discovery.tombstones import Tombstones
from cypress_creek.facts import load_bank
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.storage.db import connect, migrate
from cypress_creek.validators.names import check_company_name

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
ROOT = Path(__file__).resolve().parents[2]


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


def test_a_real_proposal_is_filtered_in_code_and_leaves_only_plain_names(tmp_path: Path) -> None:
    provider = OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 8192}
        )
    )
    bank = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
    trace = PipelineTrace()

    names = propose_names(provider, tag_profile(bank, provider.capabilities), trace=trace)

    assert isinstance(names, list)
    assert trace.calls and trace.calls[0].stage == "company"
    conn = connect(tmp_path / "db.sqlite3")
    migrate(conn)
    try:
        decisions = filter_names(names, Tombstones(conn), [])
    finally:
        conn.close()
    assert len(decisions) == len(names)
    for decision in decisions:
        if decision.outcome is NameOutcome.ACCEPTED:
            assert decision.name is not None and check_company_name(decision.name).passed
        else:
            assert decision.name is None
