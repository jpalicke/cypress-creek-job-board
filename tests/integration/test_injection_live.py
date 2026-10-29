# ABOUTME: Live test that hostile postings run through a real Ollama and score without crashing.
# ABOUTME: An unreachable server fails loudly, this test is never skipped. Quality is not judged.
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
from evals.harness.injection import ATTACKED_SUFFIX, CLEAN_SUFFIX, load_corpus
from evals.harness.score import RunMetrics, score_run

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
ROOT = Path(__file__).resolve().parents[2]
# One case from four classes keeps the run short on a small CI model.
CASES = ("direct-override-1", "output-format-1", "language-encoding-1", "hostile-names-1")


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


def test_hostile_postings_run_through_a_real_model_and_score_without_a_violation() -> None:
    corpus = load_corpus(ROOT / "evals" / "fixtures" / "injection")
    bank = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
    provider = OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 16384}
        )
    )
    names: list[str] = []
    results = []
    prompt_hashes: dict[str, str] = {}
    schema_versions: dict[str, int] = {}
    for case_id in CASES:
        fixture = corpus[case_id]
        for suffix, text in (
            (ATTACKED_SUFFIX, fixture.attacked_text),
            (CLEAN_SUFFIX, fixture.clean_text),
        ):
            name = f"{case_id}{suffix}"
            posting = Posting(
                id=name,
                source=PostingSource.PASTE,
                text=text,
                text_hash=fixture.attacked_hash
                if suffix == ATTACKED_SUFFIX
                else fixture.clean_hash,
                extractor=Extractor(name="injection-corpus", version="1"),
                created_at=datetime(2026, 10, 29, tzinfo=UTC),
            )
            trace = PipelineTrace()
            report = analyze(posting, bank, provider, backend="ollama", model=MODEL, trace=trace)
            prompt_hashes |= {call.stage: call.prompt_hash for call in trace.calls}
            schema_versions |= {call.stage: call.schema_version for call in trace.calls}
            names.append(name)
            results.append((name, posting.text_hash, report, trace))
    header = RunHeader(
        git_commit="a" * 40,
        backend="ollama",
        model=MODEL,
        prompt_hashes=prompt_hashes,
        schema_versions=schema_versions,
        fixture_set_hash="c" * 64,
        bank_hash=bank_hash(bank),
        case_ids=names,
        repeats=1,
    )
    cases = tuple(
        CaseRecord(
            run_id=header.run_id,
            case_id=name,
            repeat=1,
            posting_hash=digest,
            report=report,
            calls=trace.calls,
            validators=trace.validators,
        )
        for name, digest, report, trace in results
    )

    scored = score_run(RunState(header=header, cases=cases), {}, bank, corpus)

    assert RunMetrics.model_validate_json(scored.model_dump_json()) == scored
    assert scored.repeats_scored == 1
    expected = {corpus[case_id].case.attack_class.value for case_id in CASES}
    assert set(scored.injection) == expected
    for values in scored.injection.values():
        # The controls run after the model, so no attack may put an unsupported claim in a report.
        assert values["grounding_violations"].mean == 0.0
