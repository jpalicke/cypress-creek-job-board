# ABOUTME: The pure blacklist filter: does a candidate match a blocked company, slug or domain.
# ABOUTME: Company names are compared only through company_key. No database, no network.
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

from cypress_creek.storage.company_key import CompanyNameError, company_key


class InvalidBlacklistValue(ValueError):
    """A blacklist value that is empty or cannot be normalized into something matchable."""


class BlockReason(StrEnum):
    COMPANY_KEY = "company_key"
    SLUG = "slug"
    DOMAIN = "domain"


def normalize_slug(slug: str) -> str:
    """The one slug normalizer: trimmed and lower case. Raises InvalidBlacklistValue if empty."""
    normalized = slug.strip().lower()
    if not normalized:
        raise InvalidBlacklistValue(f"a slug cannot be empty: {slug!r}")
    return normalized


def normalize_domain(value: str) -> str:
    """The one domain normalizer. Accepts a bare host or a URL and returns a lower case,
    punycode host with no port, path, leading "www." or trailing dot. Raises
    InvalidBlacklistValue when no host is left."""
    text = value.strip().lower()
    try:
        host = urlsplit(text if "//" in text else f"//{text}").hostname
    except ValueError as error:
        raise InvalidBlacklistValue(f"not a domain: {value!r}") from error
    host = (host or "").removeprefix("www.").removesuffix(".")
    if not host:
        raise InvalidBlacklistValue(f"a domain needs a host: {value!r}")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def _normalize_company(name: str) -> str:
    try:
        return company_key(name)
    except CompanyNameError as error:
        raise InvalidBlacklistValue(f"not a usable company name: {name!r}") from error


_NORMALIZERS = {
    BlockReason.COMPANY_KEY: _normalize_company,
    BlockReason.SLUG: normalize_slug,
    BlockReason.DOMAIN: normalize_domain,
}


@dataclass(frozen=True)
class BlacklistEntry:
    """A blocked company key, board slug or domain. The value is normalized on creation."""

    match_kind: BlockReason
    value: str
    reason: str
    added_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _NORMALIZERS[self.match_kind](self.value))


@dataclass(frozen=True)
class Candidate:
    """A discovered company, with whatever board slug and domain are known."""

    name: str
    slug: str | None
    domain: str | None


def _normalized_or_none(normalizer: Callable[[str], str], value: str | None) -> str | None:
    """The normalized value, or None when it is missing or cannot be normalized."""
    if value is None:
        return None
    try:
        return normalizer(value)
    except InvalidBlacklistValue:
        return None


def is_blacklisted(candidate: Candidate, blacklist: Iterable[BlacklistEntry]) -> BlockReason | None:
    """The first reason this candidate is blocked, or None. Checks company, slug, then domain.
    A name with no company key, or a blank slug or domain, simply cannot match on that check."""
    entries = list(blacklist)
    for kind, value in (
        (BlockReason.COMPANY_KEY, candidate.name),
        (BlockReason.SLUG, candidate.slug),
        (BlockReason.DOMAIN, candidate.domain),
    ):
        key = _normalized_or_none(_NORMALIZERS[kind], value)
        if key is not None and any(e.match_kind is kind and e.value == key for e in entries):
            return kind
    return None
