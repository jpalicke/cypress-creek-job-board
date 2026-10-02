# ABOUTME: Small builders shared by the validator tests: facts, banks and requirements.
# ABOUTME: They create real model instances, so validators are always fed real shapes.
from datetime import date
from typing import Any

from cypress_creek.facts.models import Bank, Evidence, EvidenceType, Fact, Kind, Level, Share, Tag
from cypress_creek.ingest.models import Importance, Requirement, RequirementKind

POSTING = (
    "Requirements:\n"
    "- 5 years of Postgres experience.\n"
    "- Strong communication skills.\n"
    "\n"
    "Nice to have:\n"
    "- Kubernetes experience is a plus.\n"
)


def span_of(text: str, snippet: str) -> tuple[int, int]:
    start = text.index(snippet)
    return start, start + len(snippet)


def requirement(
    snippet: str = "5 years of Postgres experience",
    *,
    posting: str = POSTING,
    id: str = "R-1",
    term: str = "postgresql",
    importance: Importance = Importance.REQUIRED,
    kind: RequirementKind = RequirementKind.SKILL,
    years: int | None = 5,
) -> Requirement:
    return Requirement(
        id=id,
        text=snippet,
        span=span_of(posting, snippet),
        kind=kind,
        term=term,
        years=years,
        importance=importance,
    )


def fact(
    n: int = 1,
    *,
    claim: str = "Ran PostgreSQL in production for payments",
    kind: Kind = Kind.EMPLOYMENT,
    employer: str | None = "Initech",
    role: str | None = "Backend Engineer",
    start: date | None = date(2019, 3, 1),
    end: date | None = date(2023, 6, 30),
    verified: bool = True,
    share: Share = Share.SHAREABLE,
    tags: list[Tag] | None = None,
    **extra: Any,
) -> Fact:
    return Fact(
        id=f"F-{n:04d}",
        claim=claim,
        kind=kind,
        employer=employer,
        role=role,
        start=start,
        end=end,
        tags=tags if tags is not None else [Tag(name="postgresql", level=Level.EXPERT)],
        verified_on=date(2026, 1, 1) if verified else None,
        evidence=Evidence(type=EvidenceType.SELF_ATTESTED, pointer="note"),
        share=share,
        **extra,
    )


def bank(*facts: Fact) -> Bank:
    return Bank(facts=list(facts))
