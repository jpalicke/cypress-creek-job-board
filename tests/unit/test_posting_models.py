# ABOUTME: Tests the Posting and Requirement models, including their invariants.
# ABOUTME: Also checks that Requirement satisfies the support gate's input protocol.
from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from cypress_creek.facts.models import Evidence, EvidenceType, Fact, Kind, Level, Tag
from cypress_creek.ingest.models import (
    Extractor,
    Importance,
    Posting,
    PostingSource,
    Requirement,
    RequirementKind,
)
from cypress_creek.ingest.normalize import text_hash
from cypress_creek.scoring.aliases import AliasTable
from cypress_creek.scoring.support import Support, candidate_facts, support_ceiling

TEXT = "We need 5 years of Postgres."


def posting(**overrides: Any) -> Posting:
    fields: dict[str, Any] = {
        "id": "P-1",
        "source": PostingSource.PASTE,
        "text": TEXT,
        "text_hash": text_hash(TEXT),
        "extractor": Extractor(name="paste", version="1"),
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    fields.update(overrides)
    return Posting(**fields)


def requirement(**overrides: Any) -> Requirement:
    fields: dict[str, Any] = {
        "id": "R-1",
        "text": "5 years of Postgres",
        "span": (8, 27),
        "kind": RequirementKind.SKILL,
        "term": " Postgres ",
        "years": 5,
        "importance": Importance.REQUIRED,
    }
    fields.update(overrides)
    return Requirement(**fields)


def test_posting_defaults_have_no_origin_url_and_no_warnings() -> None:
    p = posting()
    assert p.origin_url is None
    assert p.warnings == []


def test_posting_hash_must_match_the_text() -> None:
    with pytest.raises(ValidationError, match="text_hash"):
        posting(text_hash=text_hash("something else"))


def test_posting_rejects_unknown_source_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        posting(source="carrier pigeon")
    with pytest.raises(ValidationError):
        posting(surprise=1)


def test_posting_is_frozen() -> None:
    with pytest.raises(ValidationError):
        posting().text = "other"


def test_requirement_normalizes_its_term() -> None:
    assert requirement().term == "postgres"


@pytest.mark.parametrize("bad", ["R1", "R-", "r-1", "R-x"])
def test_requirement_id_must_look_like_r_n(bad: str) -> None:
    with pytest.raises(ValidationError):
        requirement(id=bad)


@pytest.mark.parametrize("span", [(5, 5), (9, 3), (-1, 4)])
def test_requirement_span_must_be_a_forward_range(span: tuple[int, int]) -> None:
    with pytest.raises(ValidationError):
        requirement(span=span)


def test_requirement_years_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        requirement(years=0)


def test_requirement_term_must_not_be_empty_after_normalization() -> None:
    with pytest.raises(ValidationError):
        requirement(term=" ,. ")


def test_requirement_feeds_the_support_gate() -> None:
    fact = Fact(
        id="F-0001",
        claim="Ran Postgres in production",
        kind=Kind.EMPLOYMENT,
        start=date(2018, 1, 1),
        end=date(2024, 1, 1),
        tags=[Tag(name="postgresql", level=Level.EXPERT)],
        verified_on=date(2026, 1, 1),
        evidence=Evidence(type=EvidenceType.SELF_ATTESTED, pointer="note"),
    )
    aliases = AliasTable({"postgresql": ["postgres"]})
    req = requirement()
    found = candidate_facts(req, [fact], aliases)
    assert support_ceiling(req, found, date(2026, 10, 1), aliases)[0] == Support.STRONG
