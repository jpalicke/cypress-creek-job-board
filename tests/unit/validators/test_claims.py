# ABOUTME: Tests V9 (citation required) and V10 (novel term flag) including heuristic edge cases.
# ABOUTME: V10 is a conservative heuristic, so the tests pin what it flags and what it allows.
from dataclasses import dataclass

from builders import fact

from cypress_creek.facts.models import Level, Tag
from cypress_creek.validators.claims import check_citation_required, check_novel_terms, novel_terms


@dataclass(frozen=True)
class Claim:
    text: str
    fact_ids: list[str]


def test_v9_accepts_claims_that_all_cite_a_fact() -> None:
    claims = [Claim("Ran Postgres", ["F-0001"]), Claim("Led a team", ["F-0002", "F-0003"])]
    assert check_citation_required(claims).passed


def test_v9_accepts_no_claims() -> None:
    assert check_citation_required([]).passed


def test_v9_rejects_an_uncited_claim_and_names_it() -> None:
    verdict = check_citation_required([Claim("Ran Postgres", ["F-0001"]), Claim("Saved $2M", [])])
    assert not verdict.passed
    assert verdict.validator == "V9"
    assert verdict.offending == "Saved $2M"


def test_v9_ignores_a_blank_claim() -> None:
    assert check_citation_required([Claim("   ", [])]).passed


CITED = fact(
    1,
    claim="Ran PostgreSQL in production for payments",
    employer="Initech",
    role="Backend Engineer",
    tags=[
        Tag(name="postgresql", level=Level.EXPERT),
        Tag(name="machine learning", level=Level.WORKING),
    ],
)


def test_v10_allows_terms_found_in_the_cited_fact() -> None:
    text = "Ran PostgreSQL in production at Initech as a Backend Engineer"
    assert novel_terms(text, [CITED], "") == []
    assert check_novel_terms(text, [CITED], "").passed


def test_v10_allows_terms_found_in_the_requirement() -> None:
    assert novel_terms("Experienced with Kubernetes", [CITED], "Kubernetes experience") == []


def test_v10_flags_a_novel_technology_name() -> None:
    verdict = check_novel_terms("Ran PostgreSQL and Terraform", [CITED], "")
    assert not verdict.passed
    assert verdict.validator == "V10"
    assert verdict.offending == "terraform"


def test_v10_flags_a_novel_proper_noun_mid_sentence() -> None:
    assert novel_terms("I worked with Stripe on payments", [CITED], "") == ["stripe"]


def test_v10_flags_acronyms_symbols_and_mixed_case() -> None:
    found = novel_terms("Used AWS, C++, Node.js and TensorFlow", [CITED], "")
    assert found == ["aws", "c++", "node.js", "tensorflow"]


def test_v10_flags_a_mixed_script_lookalike_name() -> None:
    assert novel_terms("Worked with Initеch", [CITED], "") == ["initеch"]


def test_v10_flags_tokens_that_mix_letters_and_digits() -> None:
    assert novel_terms("Ran k8s clusters", [CITED], "") == ["k8s"]


def test_v10_does_not_flag_ordinary_capitalized_sentence_starts() -> None:
    assert novel_terms("Built reliable systems. Managed deployments.", [CITED], "") == []


def test_v10_skips_fact_id_tokens_month_names_and_plain_numbers() -> None:
    assert novel_terms("In March 2020 the work (F-0001) shipped", [CITED], "") == []


def test_v10_allows_words_from_multiword_tags() -> None:
    assert novel_terms("Applied Machine Learning daily", [CITED], "") == []


def test_v10_allows_a_possessive_of_a_known_term() -> None:
    assert novel_terms("Improved Initech's payments", [CITED], "") == []


def test_v10_flags_each_novel_term_once_in_order() -> None:
    assert novel_terms("Used Docker, Docker and Helm", [CITED], "") == ["docker", "helm"]


def test_v10_treats_a_new_line_as_a_sentence_start() -> None:
    assert novel_terms("Ran things\nDeployed things", [CITED], "") == []
