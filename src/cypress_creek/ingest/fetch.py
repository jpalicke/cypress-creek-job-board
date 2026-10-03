# ABOUTME: Fetches bounded public posting bytes through the guarded HTTP transport.
# ABOUTME: Returns provenance or a typed, redacted failure without extracting text.
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from cypress_creek import __version__
from cypress_creek.ingest.safe_http import (
    FetchLimits,
    FetchResponse,
    SafeHttpError,
    fetch_url,
)
from cypress_creek.ingest.url_guard import ReasonCode, UrlGuardError


class FetchError(Exception):
    """A caller-facing fetch failure with no hostile URL or response text."""


class BlockedByPolicy(FetchError):
    """The URL or a redirect violates the public-address policy."""

    def __init__(self, reason_code: ReasonCode) -> None:
        super().__init__("Posting URL blocked by policy")
        self.reason_code = reason_code


class FetchFailed(FetchError):
    """The connection, response, or transport protocol failed."""


class UnsupportedContent(FetchError):
    """The server did not send an allowed content type."""


class TooLarge(FetchError):
    """The response exceeded a byte or decompression limit."""


class NeedsBrowser(FetchError):
    """The server explicitly required authentication."""


class Empty(FetchError):
    """The response has no bytes to extract."""


@dataclass(frozen=True)
class FetchProvenance:
    requested_url: str
    final_url: str
    byte_count: int
    retrieved_at: datetime
    extractor_name: str
    extractor_version: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FetchResult:
    body: bytes
    content_type: str
    provenance: FetchProvenance


def _fetch_posting(
    url: str,
    limits: FetchLimits,
    *,
    transport: Callable[[str, FetchLimits], FetchResponse],
) -> FetchResult:
    """Assemble a posting result from the guarded transport's real response."""
    try:
        response = transport(url, limits)
    except UrlGuardError as error:
        raise BlockedByPolicy(error.reason_code) from None
    except SafeHttpError as error:
        if error.reason_code in {"too_large", "decompression_ratio"}:
            raise TooLarge("Posting exceeds fetch limits") from None
        if error.reason_code == "unsupported_content":
            raise UnsupportedContent("Posting content type is unsupported") from None
        if error.reason_code == "authentication_required":
            raise NeedsBrowser("Paste the posting text manually after signing in") from None
        raise FetchFailed("Posting could not be fetched") from None
    if not response.body:
        raise Empty("Posting has no content; paste the posting text manually")
    requested_host = urlsplit(url).hostname
    final_host = urlsplit(response.url).hostname
    warnings = ("cross_host_redirect",) if requested_host != final_host else ()
    provenance = FetchProvenance(
        requested_url=url,
        final_url=response.url,
        byte_count=len(response.body),
        retrieved_at=datetime.now(UTC),
        extractor_name="raw-fetch",
        extractor_version=__version__,
        warnings=warnings,
    )
    return FetchResult(response.body, response.content_type, provenance)


def fetch_posting(url: str) -> FetchResult:
    """Fetch one public posting as raw bounded bytes with provenance."""
    return _fetch_posting(
        url,
        FetchLimits(),
        transport=lambda address, cap: fetch_url(address, limits=cap),
    )
