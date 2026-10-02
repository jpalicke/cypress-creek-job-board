# ABOUTME: Validators over a set of extracted requirements: V11 cap and dedupe, V13 cue coverage.
# ABOUTME: They stop requirement stuffing, and stop requirements being silently dropped.
from collections.abc import Sequence

from cypress_creek.ingest.models import Requirement
from cypress_creek.terms import normalize_term
from cypress_creek.validators.cues import has_cue, is_importance_heading, split_sentences
from cypress_creek.validators.verdict import Verdict, fail, ok

MAX_REQUIREMENTS = 40


def dedupe_requirements(requirements: Sequence[Requirement]) -> list[Requirement]:
    """Keep the first requirement for each normalized term, then at most MAX_REQUIREMENTS."""
    seen: set[str] = set()
    kept: list[Requirement] = []
    for requirement in requirements:
        term = normalize_term(requirement.term)
        if term not in seen:
            seen.add(term)
            kept.append(requirement)
    return kept[:MAX_REQUIREMENTS]


def check_requirement_cap(requirements: Sequence[Requirement]) -> Verdict:
    """V11: at most MAX_REQUIREMENTS requirements, with no two sharing a normalized term."""
    if len(requirements) > MAX_REQUIREMENTS:
        return fail("V11", f"more than {MAX_REQUIREMENTS} requirements", str(len(requirements)))
    seen: set[str] = set()
    for requirement in requirements:
        term = normalize_term(requirement.term)
        if term in seen:
            return fail("V11", "two requirements share a normalized term", term)
        seen.add(term)
    return ok("V11")


def uncovered_cue_sentences(text: str, spans: Sequence[tuple[int, int]]) -> list[str]:
    """Posting sentences holding an importance cue word that no requirement span touches.
    Lines that are only a section heading such as "Nice to have:" are not requirements."""
    uncovered: list[str] = []
    for start, end in split_sentences(text):
        sentence = text[start:end]
        if not has_cue(sentence) or is_importance_heading(sentence):
            continue
        if not any(span_start < end and span_end > start for span_start, span_end in spans):
            uncovered.append(sentence)
    return uncovered


def check_cue_coverage(text: str, requirements: Sequence[Requirement]) -> Verdict:
    """V13: every cue sentence is covered by an extracted requirement span."""
    uncovered = uncovered_cue_sentences(text, [requirement.span for requirement in requirements])
    if uncovered:
        return fail("V13", "a sentence with an importance cue has no requirement", uncovered[0])
    return ok("V13")
