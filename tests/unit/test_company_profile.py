# ABOUTME: Tests the tag profile that company suggestion sends to a model: names and levels only.
# ABOUTME: Checked against the sample bank, so no claim text, employer or fact id can leak.
from datetime import date
from pathlib import Path

from cypress_creek.discovery.profile import TagProfile, tag_profile
from cypress_creek.facts import load_bank
from cypress_creek.facts.models import (
    Bank,
    Evidence,
    EvidenceType,
    Fact,
    Kind,
    Level,
    Share,
    Tag,
)
from cypress_creek.pipeline.prompt import build_company_prompt
from cypress_creek.pipeline.schemas import CompanyNamesOutput
from cypress_creek.providers.base import Capabilities, CostPerMtok

ROOT = Path(__file__).resolve().parents[2]
BANK = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
FREE = CostPerMtok(input=0, output=0)
LOCAL = Capabilities(context_tokens=8192, strict_schema=True, local=True, cost_per_mtok=FREE)
HOSTED = Capabilities(context_tokens=8192, strict_schema=True, local=False, cost_per_mtok=FREE)


def test_the_profile_is_tag_names_with_their_highest_level() -> None:
    profile = tag_profile(BANK, LOCAL)

    assert profile.levels["python"] is Level.EXPERT
    assert profile.levels["kubernetes"] is Level.FAMILIAR
    assert list(profile.levels) == sorted(profile.levels)


def test_the_rendered_profile_holds_no_claim_text_employer_issuer_or_fact_id() -> None:
    rendered = tag_profile(BANK, LOCAL).render()

    for fact in BANK.facts:
        assert fact.claim not in rendered
        assert fact.id not in rendered
        for private in (fact.employer, fact.issuer, fact.role):
            if private:
                assert private not in rendered
    for line in rendered.splitlines()[1:]:
        name, level = line.split(": ")
        assert level in {item.value for item in Level}
        assert name


def _fact(fact_id: str, tag: str, share: Share) -> Fact:
    return Fact(
        id=fact_id,
        claim=f"claim {fact_id}",
        kind=Kind.PROJECT,
        tags=[Tag(name=tag, level=Level.WORKING)],
        verified_on=date(2026, 1, 1),
        evidence=Evidence(type=EvidenceType.SELF_ATTESTED, pointer="me"),
        share=share,
    )


def test_a_local_only_fact_adds_no_tag_for_a_hosted_backend() -> None:
    bank = Bank(
        facts=[
            _fact("F-0001", "cobol", Share.LOCAL_ONLY),
            _fact("F-0002", "python", Share.SHAREABLE),
        ]
    )

    assert set(tag_profile(bank, HOSTED).levels) == {"python"}
    assert set(tag_profile(bank, LOCAL).levels) == {"cobol", "python"}


def test_an_unverified_fact_adds_no_tag() -> None:
    unverified = load_bank(ROOT / "evals" / "bank" / "sample_bank_unverified.yaml")
    names = {tag.name for fact in unverified.facts for tag in fact.tags}
    assert names.isdisjoint(tag_profile(unverified, LOCAL).levels)


def test_an_empty_profile_says_so() -> None:
    assert TagProfile(levels={}).render().endswith("(none)")


def test_the_company_prompt_is_a_static_system_text_plus_the_profile_and_names_no_denied_list() -> (
    None
):
    profile = tag_profile(BANK, LOCAL)
    prompt = build_company_prompt(profile.render(), CompanyNamesOutput)

    assert "python: expert" in prompt.data_block
    assert prompt.facts_block == ""
    assert prompt.boundary_token == ""
    lowered = prompt.system.lower()
    assert "denied" not in lowered and "blacklist" not in lowered and "tombstone" not in lowered
    assert profile.render() not in prompt.system
    again = build_company_prompt(tag_profile(BANK, HOSTED).render(), CompanyNamesOutput)
    assert again.prompt_hash == prompt.prompt_hash
    assert again.system == prompt.system
