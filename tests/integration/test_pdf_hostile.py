# ABOUTME: Runs the real PDF extractor over every hostile fixture and checks the listed outcome.
# ABOUTME: Hidden carriers must not reach the text, bombs and bad files fail with a typed error.
from pathlib import Path
from typing import Any

import pytest
import yaml

from cypress_creek.ingest.pdf_text import PdfError, PdfLimits, extract_pdf_text

FOLDER = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "pdf"
CASES: list[dict[str, Any]] = yaml.safe_load((FOLDER / "cases.yaml").read_text("utf-8"))["cases"]
LIMITS = PdfLimits()


def _extract(name: str) -> Any:
    return extract_pdf_text((FOLDER / name).read_bytes(), LIMITS)


def test_a_white_on_white_payload_does_not_reach_the_text() -> None:
    result = _extract("white_on_white.pdf")

    assert "ZXQ-PAYLOAD" not in result.text
    assert "Senior Data Engineer" in result.text
    assert [(w.kind, w.count) for w in result.warnings] == [("hidden_white_text", 1)]


@pytest.mark.parametrize("case", CASES, ids=[case["file"] for case in CASES])
def test_each_fixture_gives_its_expected_outcome(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "error" in expect:
        with pytest.raises(PdfError) as caught:
            _extract(case["file"])
        assert type(caught.value).__name__ == expect["error"]
        return
    result = _extract(case["file"])
    for needle in expect.get("text_includes", []):
        assert needle in result.text
    for needle in expect.get("text_excludes", []):
        assert needle not in result.text
    assert sorted(w.kind for w in result.warnings) == sorted(expect["warnings"])


def test_an_attacked_file_extracts_to_the_text_of_its_clean_twin() -> None:
    pairs = [case for case in CASES if "pair" in case]

    assert len(pairs) == 5
    for case in pairs:
        assert _extract(case["file"]).text == _extract(case["pair"]).text, case["file"]
