# ABOUTME: The company suggestion flow: ask a model for names, then filter them in code.
# ABOUTME: A name must pass V14 and miss the denied list and blacklist before anything resolves it.
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from cypress_creek.discovery.blacklist import BlacklistEntry, Candidate, is_blacklisted
from cypress_creek.discovery.tombstones import Tombstones
from cypress_creek.storage.company_key import CompanyNameError, company_key
from cypress_creek.validators.names import check_company_name


class NameOutcome(StrEnum):
    ACCEPTED = "accepted"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    DENIED = "denied"
    BLACKLISTED = "blacklisted"


@dataclass(frozen=True)
class NameDecision:
    """What happened to one model supplied name. `name` is the cleaned display name and is only
    set for an accepted one. `raw` is the model's text, kept for the report and never trusted."""

    raw: str
    outcome: NameOutcome
    reason: str
    name: str | None = None


def clean_name(raw: str) -> str:
    """NFKC and single spaces, the form that is stored and shown once V14 has passed."""
    return " ".join(unicodedata.normalize("NFKC", raw).split())


def filter_names(
    raw_names: Iterable[str], tombstones: Tombstones, blacklist: Sequence[BlacklistEntry]
) -> list[NameDecision]:
    """Decide each name, in order: V14, a company key, repeats, denied, then the blacklist.

    The denied list and the blacklist are checked here, in code, on the company key, so a case,
    spacing, punctuation, legal suffix or lookalike letter variant of a blocked company is still
    blocked. The model is never told about either list."""
    decisions: list[NameDecision] = []
    seen: set[str] = set()
    for raw in raw_names:
        verdict = check_company_name(raw)
        if not verdict.passed:
            decisions.append(NameDecision(raw, NameOutcome.INVALID, f"V14: {verdict.reason}"))
            continue
        name = clean_name(raw)
        try:
            key = company_key(name)
        except CompanyNameError:
            decisions.append(NameDecision(raw, NameOutcome.INVALID, "no usable company key"))
            continue
        if key in seen:
            decisions.append(NameDecision(raw, NameOutcome.DUPLICATE, "repeated in this answer"))
        elif tombstones.denied_company(name) is not None:
            decisions.append(NameDecision(raw, NameOutcome.DENIED, "a human denied this company"))
        elif is_blacklisted(Candidate(name=name, slug=None, domain=None), blacklist) is not None:
            decisions.append(NameDecision(raw, NameOutcome.BLACKLISTED, "on the blacklist"))
        else:
            seen.add(key)
            decisions.append(NameDecision(raw, NameOutcome.ACCEPTED, "", name))
    return decisions
