# ABOUTME: Turns a company name into the boards that exist for it, with a visible evidence grade.
# ABOUTME: Probes real adapters through the polite client. A missing board is remembered a while.
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from cypress_creek.discovery.adapters.base import AdapterError, BoardAdapter, ExistenceResult
from cypress_creek.discovery.evidence import IdentityEvidence
from cypress_creek.discovery.polite_client import PoliteFetchError
from cypress_creek.ingest.safe_http import SafeHttpError
from cypress_creek.storage.company_key import LEGAL_SUFFIXES, CompanyNameError, company_key

SLUG_FORM = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MIN_SLUG_LENGTH = 2
DEFAULT_MISSING_TTL_SECONDS = 24 * 60 * 60
_RANK = {IdentityEvidence.NONE: 0, IdentityEvidence.WEAK: 1, IdentityEvidence.STRONG: 2}


def candidate_slugs(name: str) -> list[str]:
    """A few plain lower case board names guessed from a company name, strongest guess first.

    Accents are dropped, a trailing legal suffix is ignored, and the forms are the words joined by
    hyphens, the words run together and the first word alone. A name with no ASCII letters or
    digits has none. Every slug is a safe board name, never text the model chose as a link."""
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_text.lower().replace("'", ""))
    if len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    if not words:
        return []
    forms = ["-".join(words), "".join(words)]
    if len(words) > 1:
        forms.append(words[0])
    slugs: list[str] = []
    for form in forms:
        if SLUG_FORM.match(form) and len(form) >= MIN_SLUG_LENGTH and form not in slugs:
            slugs.append(form)
    return slugs


def grade_evidence(name: str, result: ExistenceResult) -> IdentityEvidence:
    """Strong when the board reports this company's name, weak when it exists but reports no
    name (all Lever and Ashby give), none when it is missing or belongs to another company."""
    if not result.found:
        return IdentityEvidence.NONE
    if result.organization_name is None:
        return IdentityEvidence.WEAK
    try:
        same = company_key(result.organization_name) == company_key(name)
    except CompanyNameError:
        return IdentityEvidence.NONE
    return IdentityEvidence.STRONG if same else IdentityEvidence.NONE


class NegativeCache:
    """Boards found missing, kept for a while so the same name is not probed again at once."""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float]) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._missing: dict[tuple[str, str], float] = {}

    def remember_missing(self, ats: str, slug: str) -> None:
        self._missing[(ats, slug)] = self._clock() + self._ttl

    def is_missing(self, ats: str, slug: str) -> bool:
        expires = self._missing.get((ats, slug))
        if expires is None:
            return False
        if self._clock() >= expires:
            del self._missing[(ats, slug)]
            return False
        return True


@dataclass(frozen=True)
class Resolution:
    """The best board found for a name: where, how sure, and the name the board reported."""

    ats: str
    slug: str
    evidence: IdentityEvidence
    organization_name: str | None


class Resolver:
    """Probes each adapter for each candidate slug. Adapters are tried in the order given."""

    def __init__(self, adapters: Mapping[str, BoardAdapter], cache: NegativeCache) -> None:
        self._adapters = adapters
        self._cache = cache
        self.last_errors: list[str] = []

    def resolve(self, name: str) -> Resolution | None:
        """The strongest board for the name, or None when nothing exists. A failed probe is
        recorded in `last_errors` by reason code and is never treated as a missing board."""
        self.last_errors = []
        best: Resolution | None = None
        for ats, adapter in self._adapters.items():
            for slug in candidate_slugs(name):
                if self._cache.is_missing(ats, slug):
                    continue
                try:
                    result = adapter.probe(slug)
                except (AdapterError, PoliteFetchError, SafeHttpError) as error:
                    self.last_errors.append(f"{ats}/{slug}: {error.reason_code}")
                    continue
                if not result.found:
                    self._cache.remember_missing(ats, slug)
                    continue
                grade = grade_evidence(name, result)
                if grade is IdentityEvidence.NONE:
                    continue
                if best is None or _RANK[grade] > _RANK[best.evidence]:
                    best = Resolution(ats, slug, grade, result.organization_name)
        return best
