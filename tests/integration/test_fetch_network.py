# ABOUTME: Exercises posting fetches against real public HTML and PDF resources.
# ABOUTME: Verifies production provenance while allowing public content to change.
from datetime import UTC
from urllib.parse import urlsplit

import pytest

from cypress_creek import __version__
from cypress_creek.ingest.fetch import fetch_posting

HTML_URL = "https://www.usajobs.gov/job/883691200"
PDF_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"


@pytest.mark.needs_network
@pytest.mark.parametrize(
    ("url", "content_type", "prefix"),
    [(HTML_URL, "text/html", b"<"), (PDF_URL, "application/pdf", b"%PDF-")],
)
def test_public_posting_has_raw_bytes_and_provenance(
    url: str, content_type: str, prefix: bytes
) -> None:
    result = fetch_posting(url)

    assert result.content_type == content_type
    assert result.body.lstrip().startswith(prefix)
    assert result.provenance.requested_url == url
    assert urlsplit(result.provenance.final_url).scheme == "https"
    assert result.provenance.byte_count == len(result.body) > 0
    assert result.provenance.retrieved_at.tzinfo is UTC
    assert result.provenance.extractor_name == "raw-fetch"
    assert result.provenance.extractor_version == __version__
