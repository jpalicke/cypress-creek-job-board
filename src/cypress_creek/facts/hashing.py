# ABOUTME: The one definition of the fact bank hash, sha256 over the facts in canonical form.
# ABOUTME: Fact order does not matter, so reordering the bank file keeps the same hash.
import hashlib
import json

from cypress_creek.facts.models import Bank


def bank_hash(bank: Bank) -> str:
    facts = sorted((fact.model_dump(mode="json") for fact in bank.facts), key=lambda f: f["id"])
    canonical = json.dumps(facts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf8")).hexdigest()
