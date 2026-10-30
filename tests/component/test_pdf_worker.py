# ABOUTME: Runs the real PDF worker child process: limits, timeout, empty environment, no sockets.
# ABOUTME: The parent stays healthy after a bomb, a timeout and a crash, and nothing is truncated.
import json
import os
from pathlib import Path

import pytest

from cypress_creek.ingest import pdf_text
from cypress_creek.ingest.pdf_text import (
    PdfCorrupt,
    PdfLimits,
    PdfResourceLimit,
    PdfTimeout,
    PdfTooLarge,
    PdfTooManyPages,
    PdfTooMuchText,
    extract_pdf_text,
    extractor_identity,
)

FOLDER = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "pdf"


def _read(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_a_clean_pdf_returns_its_text_pages_and_the_extractor_identity() -> None:
    result = extract_pdf_text(_read("clean.pdf"))

    assert result.text.splitlines()[0] == "Senior Data Engineer"
    assert result.pages == 1
    assert result.warnings == ()
    assert result.extractor == extractor_identity()
    assert result.extractor.name == "pypdf"


def test_the_child_has_an_empty_environment_and_cannot_open_a_socket() -> None:
    os.environ["CYPRESS_CREEK_PROBE_VALUE"] = "must-not-leak"
    try:
        out = pdf_text.run_worker(PdfLimits(), b"", "--self-check")
    finally:
        del os.environ["CYPRESS_CREEK_PROBE_VALUE"]

    report = json.loads(out)
    # Python itself adds LC_CTYPE when it coerces the locale; nothing else is there.
    assert set(report["env"]) <= {"LC_CTYPE"}
    assert "must-not-leak" not in json.dumps(report)
    assert report["socket_blocked"] is True
    assert report["limits_applied"] is True


def test_a_file_over_the_size_cap_is_refused_before_any_child_starts() -> None:
    with pytest.raises(PdfTooLarge):
        extract_pdf_text(_read("clean.pdf"), PdfLimits(max_bytes=100))


def test_a_page_count_over_the_cap_is_refused_not_truncated() -> None:
    with pytest.raises(PdfTooManyPages):
        extract_pdf_text(_read("clean.pdf"), PdfLimits(max_pages=0))


def test_text_over_the_character_cap_is_refused_not_cut() -> None:
    with pytest.raises(PdfTooMuchText):
        extract_pdf_text(_read("clean.pdf"), PdfLimits(max_chars=20))


def test_a_run_that_takes_too_long_is_killed_with_a_typed_error() -> None:
    with pytest.raises(PdfTimeout):
        extract_pdf_text(_read("clean.pdf"), PdfLimits(timeout_seconds=0.01))


def test_the_memory_limit_stops_the_bomb_even_when_the_decode_cap_is_off() -> None:
    limits = PdfLimits(max_decoded_bytes=2_000_000_000, memory_bytes=400 * 1024 * 1024)

    with pytest.raises(PdfResourceLimit):
        extract_pdf_text(_read("decompression_bomb.pdf"), limits)


def test_the_parent_is_still_healthy_after_each_failure() -> None:
    for name, error in (
        ("decompression_bomb.pdf", PdfResourceLimit),
        ("truncated.pdf", PdfCorrupt),
    ):
        with pytest.raises(error):
            extract_pdf_text(_read(name))
        assert extract_pdf_text(_read("clean.pdf")).text.startswith("Senior Data Engineer")


def test_a_worker_that_crashes_gives_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_text, "WORKER_MODULE", "cypress_creek.ingest.no_such_worker")

    with pytest.raises(PdfResourceLimit):
        extract_pdf_text(_read("clean.pdf"))
