# ABOUTME: Exercises posting fetches from an independent Python consumer process.
# ABOUTME: Covers real public HTTPS and blocked loopback through production entry points.
import json
import subprocess
import sys

import pytest

PDF_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
HTML_URL = "https://www.usajobs.gov/job/883691200"

CONSUMER = """
import json
import sys
from cypress_creek.ingest.fetch import BlockedByPolicy, fetch_posting

try:
    result = fetch_posting(sys.argv[1])
except BlockedByPolicy as error:
    print(json.dumps({'error': type(error).__name__, 'reason_code': error.reason_code}))
    raise SystemExit(2) from None
print(json.dumps({
    'content_type': result.content_type,
    'byte_count': result.provenance.byte_count,
    'final_url': result.provenance.final_url,
    'extractor_name': result.provenance.extractor_name,
}))
"""

HTML_CONSUMER = """
import json
import sys
from cypress_creek.ingest.fetch import fetch_posting
from cypress_creek.ingest.html_text import html_to_text

fetched = fetch_posting(sys.argv[1])
extracted = html_to_text(fetched.body)
print(json.dumps({
    'has_requirements': 'Requirements' in extracted.text.splitlines(),
    'has_script_markup': '<script' in extracted.text.lower(),
    'hidden_count': extracted.warnings[0].count if extracted.warnings else 0,
}))
"""


def _consume(url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", CONSUMER, url],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )


@pytest.mark.needs_network
def test_consumer_fetches_public_pdf() -> None:
    result = _consume(PDF_URL)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["content_type"] == "application/pdf"
    assert payload["byte_count"] > 0
    assert payload["final_url"] == PDF_URL
    assert payload["extractor_name"] == "raw-fetch"


@pytest.mark.needs_network
def test_consumer_extracts_public_html() -> None:
    result = subprocess.run(
        [sys.executable, "-c", HTML_CONSUMER, HTML_URL],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["has_requirements"] is True
    assert payload["has_script_markup"] is False
    assert payload["hidden_count"] > 0


def test_consumer_rejects_loopback_without_echoing_url() -> None:
    url = "http://127.0.0.1/private"
    result = _consume(url)
    assert result.returncode == 2, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": "BlockedByPolicy",
        "reason_code": "unsafe_address",
    }
    assert url not in result.stdout
