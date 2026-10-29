# ABOUTME: Live test that cue sentences a real Ollama extraction skips reach the gap report.
# ABOUTME: An unreachable server fails loudly, this test is never skipped.
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from cypress_creek.config import parse_settings
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.pipeline.render import render_text
from cypress_creek.pipeline.run import analyze
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.ollama import DEFAULT_BASE_URL
from cypress_creek.validators.requirements import uncovered_cue_spans

pytestmark = pytest.mark.live

MODEL = os.environ.get("CYPRESS_CREEK_LIVE_MODEL", "qwen3.5:0.8b")
BASE_URL = os.environ.get("CYPRESS_CREEK_LIVE_BASE_URL", DEFAULT_BASE_URL)
FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"


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


def test_uncovered_cue_sentences_match_the_validator_the_trace_and_the_rendered_count() -> None:
    text = (FIXTURES / "posting.txt").read_text(encoding="utf-8")
    posting = Posting(
        id="P-1",
        source=PostingSource.PASTE,
        text=text,
        text_hash=text_hash(text),
        extractor=Extractor(name="paste", version="1"),
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    provider = OllamaProvider(
        parse_settings(
            {"provider": "ollama", "model": MODEL, "base_url": BASE_URL, "context_tokens": 4096}
        )
    )
    trace = PipelineTrace()

    report = analyze(posting, Bank(facts=[]), provider, backend="ollama", model=MODEL, trace=trace)

    spans = [(text.index(row.text), text.index(row.text) + len(row.text)) for row in report.rows]
    expected = uncovered_cue_spans(text, spans)
    assert [item.span for item in report.not_assessed] == expected
    for item in report.not_assessed:
        assert item.text == text[item.span[0] : item.span[1]]
    verdicts = [
        record.verdict
        for record in trace.validators
        if record.stage == "extract" and record.verdict.validator == "V13"
    ]
    assert len(verdicts) == 1
    assert verdicts[0].passed is (not report.not_assessed)
    rendered = render_text(report)
    if report.not_assessed:
        assert f" {len(report.not_assessed)} cue " in rendered
    else:
        assert "cue sentence" not in rendered
