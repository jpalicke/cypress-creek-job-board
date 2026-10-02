# ABOUTME: Tests the deterministic support gate: candidate facts, merged years and level ceilings.
# ABOUTME: Includes Hypothesis properties for monotonicity and the familiar level ceiling.
from dataclasses import dataclass
from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.facts.models import Evidence, EvidenceType, Fact, Kind, Level, Tag
from cypress_creek.scoring.aliases import AliasTable
from cypress_creek.scoring.support import (
    Gate,
    Support,
    candidate_facts,
    merged_years,
    support_ceiling,
)

TODAY = date(2026, 10, 1)
ALIASES = AliasTable({"postgresql": ["postgres"], "python": ["py"]})
ORDER = [Support.NONE, Support.PARTIAL, Support.STRONG]


@dataclass(frozen=True)
class Req:
    term: str
    kind: str = "skill"
    years: int | None = None


def fact(
    n: int,
    tag: str,
    level: Level = Level.EXPERT,
    start: date | None = None,
    end: date | None = None,
    kind: Kind = Kind.EMPLOYMENT,
) -> Fact:
    return Fact(
        id=f"F-{n:04d}",
        claim="Did a thing",
        kind=kind,
        start=start,
        end=end,
        tags=[Tag(name=tag, level=level)],
        verified_on=date(2026, 1, 1),
        evidence=Evidence(type=EvidenceType.SELF_ATTESTED, pointer="note"),
    )


def test_postgres_requirement_makes_the_postgresql_fact_a_candidate() -> None:
    facts = [fact(1, "postgresql"), fact(2, "python")]
    found = candidate_facts(Req("postgres"), facts, ALIASES)
    assert [f.id for f in found] == ["F-0001"]


def test_no_candidate_gives_none_and_names_the_gate() -> None:
    support, gate = support_ceiling(Req("cobol"), [], TODAY)
    assert (support, gate) == (Support.NONE, Gate.NO_CANDIDATE)


def test_term_match_without_years_is_strong() -> None:
    support, gate = support_ceiling(Req("postgres"), [fact(1, "postgresql")], TODAY)
    assert (support, gate) == (Support.STRONG, Gate.TERM_MATCH)


def test_overlapping_roles_count_as_the_merged_span() -> None:
    a = fact(1, "python", start=date(2020, 1, 1), end=date(2023, 1, 1))
    b = fact(2, "python", start=date(2021, 1, 1), end=date(2024, 1, 1))
    assert round(merged_years([a, b], TODAY), 1) == 4.0
    support, gate = support_ceiling(Req("python", years=5), [a, b], TODAY)
    assert (support, gate) == (Support.PARTIAL, Gate.YEARS_BELOW)


def test_merged_years_meeting_the_requirement_is_strong() -> None:
    a = fact(1, "python", start=date(2018, 1, 1), end=date(2021, 1, 1))
    b = fact(2, "python", start=date(2021, 1, 1), end=date(2024, 1, 1))
    assert support_ceiling(Req("python", years=5), [a, b], TODAY) == (
        Support.STRONG,
        Gate.YEARS_MET,
    )


def test_open_ended_role_runs_to_today() -> None:
    a = fact(1, "python", start=date(2016, 10, 1))
    assert round(merged_years([a], TODAY)) == 10


def test_missing_dates_give_partial_at_most() -> None:
    support, gate = support_ceiling(Req("python", years=3), [fact(1, "python")], TODAY)
    assert (support, gate) == (Support.PARTIAL, Gate.NO_DATES)


def test_familiar_level_caps_at_partial() -> None:
    support, gate = support_ceiling(Req("python"), [fact(1, "python", Level.FAMILIAR)], TODAY)
    assert (support, gate) == (Support.PARTIAL, Gate.FAMILIAR_LEVEL)


def test_education_matches_only_education_facts() -> None:
    degree = fact(1, "computer science", kind=Kind.EDUCATION)
    job = fact(2, "computer science")
    found = candidate_facts(Req("computer science", kind="education"), [degree, job], ALIASES)
    assert [f.id for f in found] == ["F-0001"]


def test_certification_matches_only_certification_facts() -> None:
    cert = fact(1, "cka", kind=Kind.CERTIFICATION)
    job = fact(2, "cka")
    found = candidate_facts(Req("CKA", kind="certification"), [cert, job], ALIASES)
    assert [f.id for f in found] == ["F-0001"]


def test_skill_requirement_ignores_education_facts() -> None:
    degree = fact(1, "python", kind=Kind.EDUCATION)
    assert candidate_facts(Req("python"), [degree], ALIASES) == []


def test_support_is_deterministic() -> None:
    facts = [fact(1, "python", start=date(2020, 1, 1), end=date(2022, 1, 1))]
    first = support_ceiling(Req("python", years=2), facts, TODAY)
    assert first == support_ceiling(Req("python", years=2), facts, TODAY)


@given(
    years=st.integers(min_value=1, max_value=15),
    held=st.integers(min_value=0, max_value=5000),
)
def test_support_is_monotone_in_days_held(years: int, held: int) -> None:
    def rank(days: int) -> int:
        start = date(2000, 1, 1)
        end = date.fromordinal(start.toordinal() + days)
        facts = [fact(1, "python", start=start, end=end)]
        return ORDER.index(support_ceiling(Req("python", years=years), facts, TODAY)[0])

    assert rank(held) <= rank(held + 365)


@given(
    years=st.one_of(st.none(), st.integers(min_value=1, max_value=15)),
    days=st.integers(min_value=0, max_value=9000),
)
def test_familiar_level_never_exceeds_partial(years: int | None, days: int) -> None:
    start = date(2000, 1, 1)
    end = date.fromordinal(start.toordinal() + days)
    facts = [fact(1, "python", Level.FAMILIAR, start, end)]
    support, _ = support_ceiling(Req("python", years=years), facts, TODAY)
    assert ORDER.index(support) <= ORDER.index(Support.PARTIAL)
