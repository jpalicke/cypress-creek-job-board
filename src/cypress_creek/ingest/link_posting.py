# ABOUTME: Turns a fetched link into a Posting: HTML or plain text become text, PDF is not read yet.
# ABOUTME: The fetch itself stays in fetch.py, so the SSRF guard and its limits apply unchanged.
from dataclasses import dataclass
from datetime import datetime

from cypress_creek import __version__
from cypress_creek.ingest.build import build_posting
from cypress_creek.ingest.fetch import FetchResult, fetch_posting
from cypress_creek.ingest.html_text import HtmlTextWarning, html_to_text
from cypress_creek.ingest.models import Extractor, Posting, PostingSource

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
TEXT_TYPES = frozenset({"text/plain"})
PDF_TYPE = "application/pdf"


class PdfNotSupported(Exception):
    """PDF text extraction is not built yet. The caller should ask for the text to be pasted."""


@dataclass(frozen=True)
class LinkPosting:
    posting: Posting
    extraction_warnings: tuple[HtmlTextWarning, ...]
    fetch_warnings: tuple[str, ...]


def posting_from_fetch(result: FetchResult, *, now: datetime | None = None) -> LinkPosting:
    """Convert fetched bytes to a normalized Posting. HTML goes through the hostile-HTML parser."""
    content_type = result.content_type
    if content_type == PDF_TYPE:
        raise PdfNotSupported
    if content_type in HTML_TYPES:
        extracted = html_to_text(result.body)
        raw, warnings = extracted.text, extracted.warnings
        extractor = Extractor(name="html-text", version=__version__)
    else:
        raw, warnings = result.body.decode("utf-8", errors="replace"), ()
        extractor = Extractor(name="plain-text", version=__version__)
    posting = build_posting(
        raw,
        PostingSource.LINK,
        extractor,
        origin_url=result.provenance.final_url,
        now=now,
    )
    return LinkPosting(posting, warnings, result.provenance.warnings)


def posting_from_url(url: str) -> LinkPosting:
    """Fetch one public link through the guarded transport and build its Posting."""
    return posting_from_fetch(fetch_posting(url))
