# ABOUTME: Validators for cited fact IDs: V4 fact exists, V5 fact verified, V6 fact shareable.
# ABOUTME: Pure functions over the bank, so a fabricated or private citation cannot get through.
from collections.abc import Sequence

from cypress_creek.facts.models import Bank, Fact, Share
from cypress_creek.validators.verdict import Verdict, fail, ok


def _facts_by_id(bank: Bank) -> dict[str, Fact]:
    return {fact.id: fact for fact in bank.facts}


def check_fact_exists(cited_ids: Sequence[str], bank: Bank) -> Verdict:
    """V4: every cited ID is in the bank."""
    known = _facts_by_id(bank)
    for fact_id in cited_ids:
        if fact_id not in known:
            return fail("V4", "cited fact is not in the bank", fact_id)
    return ok("V4")


def check_fact_verified(cited_ids: Sequence[str], bank: Bank) -> Verdict:
    """V5: every cited fact has verified_on. An unknown ID cannot be verified, so it fails."""
    known = _facts_by_id(bank)
    for fact_id in cited_ids:
        fact = known.get(fact_id)
        if fact is None or not fact.is_verified:
            return fail("V5", "cited fact is not verified", fact_id)
    return ok("V5")


def check_fact_shareable(fact_ids: Sequence[str], bank: Bank, *, hosted: bool) -> Verdict:
    """V6: no local_only fact was sent to, or cited from, a hosted backend. Pass every ID that
    was sent or cited. Unknown IDs are V4's concern."""
    if not hosted:
        return ok("V6")
    known = _facts_by_id(bank)
    for fact_id in fact_ids:
        fact = known.get(fact_id)
        if fact is not None and fact.share == Share.LOCAL_ONLY:
            return fail("V6", "local_only fact used with a hosted backend", fact_id)
    return ok("V6")
