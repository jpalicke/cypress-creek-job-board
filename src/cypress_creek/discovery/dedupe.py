# ABOUTME: Conservative listing dedupe: the same listing id first, then an exact fingerprint.
# ABOUTME: A near match or an ambiguous group stays separate, because a false merge hides a job.
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from cypress_creek.discovery.adapters.base import Listing
from cypress_creek.discovery.tombstones import normalize_board

# Punctuation is dropped except where it changes the meaning of a title, as in C# or C++.
_KEPT_PUNCTUATION = frozenset("#")


def fingerprint_text(text: str) -> str:
    """NFKC, casefold, punctuation to spaces (C# and C++ keep their marks), single spaces."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    spaced = "".join(
        " "
        if char.isspace()
        or (unicodedata.category(char).startswith("P") and char not in _KEPT_PUNCTUATION)
        else char
        for char in folded
    )
    return " ".join(spaced.split())


@dataclass(frozen=True)
class MergedListing:
    """One listing after dedupe, with the source ids and urls of everything merged into it.

    `listing.posted_at` is the earliest posted_at among the merged listings. `urls` and
    `source_ids` are sorted, so the result does not depend on input order.
    """

    listing: Listing
    urls: tuple[str, ...]
    source_ids: tuple[str, ...]


def dedupe(
    listings: Sequence[Listing], company_keys: Mapping[tuple[str, str], str]
) -> list[MergedListing]:
    """Merge duplicates conservatively. company_keys maps a normalized (ats, slug) to its key.

    Level one keeps one listing per listing id. Level two merges listings from different sources
    whose company key, title and location fingerprints are all equal. A fingerprint group in
    which one source appears twice is ambiguous and merges nothing. A listing whose board has no
    company key never merges across sources. The result is sorted by listing id.
    """
    by_id: dict[str, Listing] = {}
    for listing in listings:
        current = by_id.get(listing.id)
        if current is None or _recency(listing) > _recency(current):
            by_id[listing.id] = listing
    groups: dict[tuple[str, str, str], list[Listing]] = defaultdict(list)
    loose: list[Listing] = []
    for listing in by_id.values():
        company = company_keys.get(normalize_board(listing.ats, listing.slug))
        if company is None:
            loose.append(listing)
        else:
            groups[
                (company, fingerprint_text(listing.title), fingerprint_text(listing.location))
            ].append(listing)
    merged = [_merge([listing]) for listing in loose]
    for members in groups.values():
        if len({member.ats for member in members}) == len(members):
            merged.append(_merge(members))
        else:
            merged.extend(_merge([member]) for member in members)
    return sorted(merged, key=lambda item: item.listing.id)


def _recency(listing: Listing) -> tuple[datetime, str, str, str, str, str, str]:
    """Which copy of one listing id wins: the latest fetch, then every field, so it is total."""
    posted = listing.posted_at.isoformat() if listing.posted_at else ""
    return (
        listing.fetched_at,
        listing.content_hash,
        listing.url,
        listing.title,
        listing.location,
        listing.content_text,
        posted,
    )


def _merge(members: list[Listing]) -> MergedListing:
    ordered = sorted(members, key=lambda member: member.id)
    dates = [member.posted_at for member in ordered if member.posted_at is not None]
    keeper = replace(ordered[0], posted_at=min(dates) if dates else None)
    return MergedListing(
        listing=keeper,
        urls=tuple(sorted(member.url for member in ordered)),
        source_ids=tuple(member.id for member in ordered),
    )
