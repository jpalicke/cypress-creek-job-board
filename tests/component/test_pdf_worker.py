# ABOUTME: Runs the real PDF worker child process: limits, timeout, empty environment, no sockets.
# ABOUTME: The parent stays healthy after a bomb, a timeout and a crash, and nothing is truncated.
import json
import os
import sys
import time
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
    # Python itself adds LC_CTYPE when it coerces the locale, and Windows needs SYSTEMROOT to start.
    assert set(report["env"]) <= {"LC_CTYPE", "SYSTEMROOT"}
    assert "must-not-leak" not in json.dumps(report)
    assert report["socket_blocked"] is True
    assert report["limits_applied"] is (os.name == "posix")


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


def test_the_memory_limit_stops_the_bomb_where_it_exists_and_the_decode_cap_where_it_does_not() -> (
    None
):
    report = json.loads(pdf_text.run_worker(PdfLimits(), b"", "--self-check"))
    if os.name == "posix":
        assert report["limits_applied"] is True
        limits = PdfLimits(max_decoded_bytes=2_000_000_000, memory_bytes=400 * 1024 * 1024)
    else:
        # No POSIX resource limits: the documented fallback is the decoded size cap and the timeout.
        assert report["limits_applied"] is False
        limits = PdfLimits()

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


def _crash(message: str, size: int = 0) -> object:
    code = f"import sys\nsys.stderr.write({message!r} + 'x' * {size})\nsys.exit(3)\n"
    return lambda _limits, *_flags: [sys.executable, "-I", "-c", code]


def test_a_crashing_worker_keeps_the_tail_of_its_stderr_in_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_text, "worker_command", _crash("Traceback: boom"))

    with pytest.raises(PdfResourceLimit) as caught:
        extract_pdf_text(_read("clean.pdf"))

    assert "boom" in str(caught.value) and "exit 3" in str(caught.value)


def test_only_the_last_two_kilobytes_of_stderr_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_text, "worker_command", _crash("HEAD-", 10_000))

    with pytest.raises(PdfResourceLimit) as caught:
        extract_pdf_text(_read("clean.pdf"))

    assert "HEAD-" not in str(caught.value)
    assert len(str(caught.value)) < 3000


def test_the_stderr_tail_is_logged_and_never_sent_to_an_api_caller(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    from api_support import ApiClient, csrf_headers

    from cypress_creek.api.app import create_app

    monkeypatch.setattr(pdf_text, "worker_command", _crash("Traceback: boom"))
    client = ApiClient(create_app(None, static_dir=None, database_path=tmp_path / "x.db"))
    headers = csrf_headers(client, {"content-type": "application/pdf"})

    with caplog.at_level("WARNING"):
        response = client.post("/api/postings", content=_read("clean.pdf"), headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pdf_resource_limit"
    assert "boom" not in response.text
    assert any("boom" in record.getMessage() for record in caplog.records)


def test_a_worker_that_floods_its_output_is_stopped_while_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flood = "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)\n    sys.stdout.flush()\n"
    monkeypatch.setattr(
        pdf_text, "worker_command", lambda _limits, *_flags: [sys.executable, "-I", "-c", flood]
    )
    started = time.monotonic()

    with pytest.raises(PdfResourceLimit):
        extract_pdf_text(_read("clean.pdf"), PdfLimits(max_chars=1000, timeout_seconds=30))

    assert time.monotonic() - started < 10


def _answer_then_linger(seconds: float) -> object:
    code = (
        "import os, sys, time\n"
        "sys.stdout.write('{\"ok\": true}')\n"
        "sys.stdout.flush()\n"
        "os.close(1)\n"
        f"time.sleep({seconds})\n"
    )
    return lambda _limits, *_flags: [sys.executable, "-I", "-c", code]


def test_a_good_answer_is_kept_when_the_child_is_still_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # stdout reaches end of file as soon as the child closes it, which can be before the process
    # has exited. Killing it then gave exit code 1 on Windows and 9 on Linux for a good answer.
    monkeypatch.setattr(pdf_text, "worker_command", _answer_then_linger(1.0))

    assert pdf_text.run_worker(PdfLimits(), b"") == b'{"ok": true}'


def test_a_child_that_never_finishes_is_killed_at_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_text, "worker_command", _answer_then_linger(30))
    started = time.monotonic()

    with pytest.raises(PdfTimeout):
        pdf_text.run_worker(PdfLimits(timeout_seconds=1.5), b"")

    assert time.monotonic() - started < 10
