# ABOUTME: Turns a fetched link into a Posting: HTML, plain text and PDF become text.
# ABOUTME: The fetch itself stays in fetch.py, so the SSRF guard and its limits apply unchanged.
from dataclasses import dataclass
from datetime import datetime

from cypress_creek import __version__
from cypress_creek.ingest.build import build_posting
from cypress_creek.ingest.fetch import FetchResult, fetch_posting
from cypress_creek.ingest.html_text import HtmlTextWarning, html_to_text
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.ingest.pdf_text import extract_pdf_text

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
TEXT_TYPES = frozenset({"text/plain"})
PDF_TYPE = "application/pdf"


@dataclass(frozen=True)
class LinkPosting:
    posting: Posting
    extraction_warnings: tuple[HtmlTextWarning, ...]
    fetch_warnings: tuple[str, ...]


def posting_from_fetch(result: FetchResult, *, now: datetime | None = None) -> LinkPosting:
    """Convert fetched bytes to a normalized Posting. HTML goes through the hostile-HTML parser."""
    content_type = result.content_type
    if content_type == PDF_TYPE:
        return posting_from_pdf(
            result.body,
            PostingSource.LINK,
            origin_url=result.provenance.final_url,
            fetch_warnings=result.provenance.warnings,
            now=now,
        )
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


def posting_from_pdf(
    data: bytes,
    source: PostingSource,
    *,
    origin_url: str | None = None,
    fetch_warnings: tuple[str, ...] = (),
    now: datetime | None = None,
) -> LinkPosting:
    """Read a PDF in the limited child process and keep only its visible text. Raises PdfError."""
    extracted = extract_pdf_text(data)
    posting = build_posting(
        extracted.text, source, extracted.extractor, origin_url=origin_url, now=now
    )
    warnings = tuple(HtmlTextWarning(w.kind, w.count) for w in extracted.warnings)
    return LinkPosting(posting, warnings, fetch_warnings)


def posting_from_url(url: str) -> LinkPosting:
    """Fetch one public link through the guarded transport and build its Posting."""
    return posting_from_fetch(fetch_posting(url))
