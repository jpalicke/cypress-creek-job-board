# ABOUTME: Tests V4 (fact exists), V5 (fact verified) and V6 (fact shareable) against real banks.
# ABOUTME: Covers empty citation lists, unknown IDs, mixed good and bad IDs and hosted backends.
from builders import bank, fact

from cypress_creek.facts.models import Share
from cypress_creek.validators.citations import (
    check_fact_exists,
    check_fact_shareable,
    check_fact_verified,
)

BANK = bank(
    fact(1),
    fact(2, verified=False),
    fact(3, share=Share.LOCAL_ONLY),
)


def test_v4_accepts_ids_in_the_bank() -> None:
    assert check_fact_exists(["F-0001", "F-0002"], BANK).passed


def test_v4_accepts_an_empty_citation_list() -> None:
    assert check_fact_exists([], BANK).passed


def test_v4_rejects_a_fabricated_id_and_names_it() -> None:
    verdict = check_fact_exists(["F-0001", "F-9999"], BANK)
    assert not verdict.passed
    assert verdict.validator == "V4"
    assert verdict.offending == "F-9999"


def test_v4_rejects_ids_that_only_look_like_ids() -> None:
    assert not check_fact_exists(["f-0001"], BANK).passed
    assert not check_fact_exists(["F-0001 "], BANK).passed


def test_v5_accepts_verified_facts() -> None:
    assert check_fact_verified(["F-0001", "F-0003"], BANK).passed


def test_v5_rejects_an_unverified_fact() -> None:
    verdict = check_fact_verified(["F-0001", "F-0002"], BANK)
    assert not verdict.passed
    assert verdict.offending == "F-0002"


def test_v5_rejects_an_unknown_id_because_it_cannot_be_verified() -> None:
    assert not check_fact_verified(["F-9999"], BANK).passed


def test_v5_accepts_an_empty_citation_list() -> None:
    assert check_fact_verified([], BANK).passed


def test_v6_allows_local_only_facts_on_a_local_backend() -> None:
    assert check_fact_shareable(["F-0003"], BANK, hosted=False).passed


def test_v6_rejects_a_local_only_fact_on_a_hosted_backend() -> None:
    verdict = check_fact_shareable(["F-0001", "F-0003"], BANK, hosted=True)
    assert not verdict.passed
    assert verdict.offending == "F-0003"


def test_v6_allows_shareable_facts_on_a_hosted_backend() -> None:
    assert check_fact_shareable(["F-0001"], BANK, hosted=True).passed


def test_v6_leaves_unknown_ids_to_v4() -> None:
    assert check_fact_shareable(["F-9999"], BANK, hosted=True).passed
