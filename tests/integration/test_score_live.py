# ABOUTME: Live test that a real Ollama run over two labeled fixtures scores into valid metrics.
# ABOUTME: An unreachable server fails loudly, this test is never skipped. Values are not asserted.
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from cypress_creek.config import parse_settings
from cypress_creek.eval_records import CaseRecord, RunHeader, RunState
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.pipeline.run import analyze
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from evals.harness.fixtures import discover_fixtures, fixture_set_hash, load_fixture
from evals.harness.metrics import METRICS
from evals.harness.score import RunMetrics, score_run

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
ROOT = Path(__file__).resolve().parents[2]
FIXTURE_COUNT = 2


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


def test_a_real_run_over_labeled_fixtures_scores_into_valid_metrics() -> None:
    fixtures = [load_fixture(path) for path in discover_fixtures(ROOT / "evals" / "fixtures")]
    chosen = fixtures[:FIXTURE_COUNT]
    bank = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
    provider = OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 16384}
        )
    )
    cases = []
    prompt_hashes: dict[str, str] = {}
    schema_versions: dict[str, int] = {}
    for fixture in chosen:
        posting = Posting(
            id=fixture.meta.fixture_id,
            source=PostingSource.PASTE,
            text=fixture.text,
            text_hash=fixture.text_hash,
            extractor=Extractor(name="fixture", version="1"),
            created_at=datetime(2026, 10, 29, tzinfo=UTC),
        )
        trace = PipelineTrace()
        report = analyze(posting, bank, provider, backend="ollama", model=MODEL, trace=trace)
        prompt_hashes |= {call.stage: call.prompt_hash for call in trace.calls}
        schema_versions |= {call.stage: call.schema_version for call in trace.calls}
        cases.append((fixture, report, trace))
    header = RunHeader(
        git_commit="a" * 40,
        backend="ollama",
        model=MODEL,
        prompt_hashes=prompt_hashes,
        schema_versions=schema_versions,
        fixture_set_hash=fixture_set_hash(chosen),
        bank_hash=bank_hash(bank),
        case_ids=[fixture.meta.fixture_id for fixture in chosen],
        repeats=1,
    )
    records = tuple(
        CaseRecord(
            run_id=header.run_id,
            case_id=fixture.meta.fixture_id,
            repeat=1,
            posting_hash=fixture.text_hash,
            report=report,
            calls=trace.calls,
            validators=trace.validators,
        )
        for fixture, report, trace in cases
    )

    result = score_run(
        RunState(header=header, cases=records), {f.meta.fixture_id: f for f in chosen}, bank
    )

    assert RunMetrics.model_validate_json(result.model_dump_json()) == result
    assert result.repeats_scored == 1
    assert set(result.metrics) == {metric.name for metric in METRICS}
    for metric in METRICS:
        value = result.metrics[metric.name]
        if metric.is_rate and value.mean is not None:
            assert 0.0 <= value.mean <= 1.0
    # A report that passed verify_report cites real, verified facts and stays under its ceiling.
    assert result.metrics["fabricated_ids"].mean == 0.0
    assert result.metrics["raises_after_clamp"].mean == 0.0
