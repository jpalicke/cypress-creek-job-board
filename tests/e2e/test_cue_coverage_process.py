# ABOUTME: Runs the text report in a separate Python process on a posting with an omitted cue.
# ABOUTME: The count beside the score and the offset line come from production code only.
import subprocess
import sys

CONSUMER = """
import sys
from datetime import UTC, date, datetime

from cypress_creek.config import parse_settings
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import (
    Extractor, Importance, Posting, PostingSource, Requirement, RequirementKind,
)
from cypress_creek.pipeline.extract import ExtractionResult, ExtractionStatus
from cypress_creek.pipeline.render import render_text
from cypress_creek.pipeline.run import assess
from cypress_creek.providers import OllamaProvider
from cypress_creek.providers.base import Usage

accepted = "You must know Python."
omitted = "Postgres is required."
text = f"Requirements:\\n{accepted}\\n{omitted}"
posting = Posting(
    id="P-1", source=PostingSource.PASTE, text=text, text_hash=text_hash(text),
    extractor=Extractor(name="paste", version="1"),
    created_at=datetime(2024, 6, 1, tzinfo=UTC),
)
start = text.index(accepted)
requirement = Requirement(
    id="R-1", text=accepted, span=(start, start + len(accepted)),
    kind=RequirementKind.SKILL, term="python", importance=Importance.REQUIRED,
)
extraction = ExtractionResult(
    status=ExtractionStatus.OK, requirements=[requirement], dropped=[],
    not_assessed_count=0, failure=None, usage=Usage(input_tokens=1, output_tokens=1),
    prompt_hash="a" * 64, schema_version=1,
)
provider = OllamaProvider(
    parse_settings({"provider": "ollama", "model": "m", "base_url": "http://127.0.0.1:9"})
)
report = assess(
    posting, extraction, Bank(facts=[]), provider,
    backend="ollama", model="m", today=date(2024, 6, 1),
)
sys.stdout.write(render_text(report) + "\\n" + str(text.index(omitted)) + "\\n")
"""


def test_the_text_report_shows_the_count_beside_the_score_and_the_offset_line() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CONSUMER], capture_output=True, text=True, timeout=60, check=False
    )

    assert result.returncode == 0, result.stderr
    *report_lines, offset = result.stdout.splitlines()
    score_line = next(line for line in report_lines if line.startswith("Score:"))
    assert score_line.endswith("1 cue sentence not assessed; the score does not cover them.")
    assert f"Cue sentence not assessed at offset {offset}: Postgres is required." in report_lines
    assert result.stderr == ""
