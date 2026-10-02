# ABOUTME: Validators V9 citation required and V10 novel term flag for generated text.
# ABOUTME: V10 is a conservative heuristic, it flags suspicious terms and never proves a lie.
import re
from collections.abc import Iterable, Sequence
from typing import Protocol

from cypress_creek.facts.models import Fact
from cypress_creek.terms import normalize_term
from cypress_creek.validators.verdict import Verdict, fail, ok

_TOKEN = re.compile(r"[^\s,;:()\[\]{}\"“”]+")
_SENTENCE_END = re.compile(r"[.!?]$")
_ID = re.compile(r"^[fr]-\d+$")
_COMMON_CAPITALIZED = frozenset(
    [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "i",
    ]
)


class Claim(Protocol):
    """A sentence of generated text with the fact IDs it cites."""

    @property
    def text(self) -> str: ...

    @property
    def fact_ids(self) -> Sequence[str]: ...


def check_citation_required(claims: Iterable[Claim]) -> Verdict:
    """V9: every non-blank claim cites at least one fact ID."""
    for claim in claims:
        if claim.text.strip() and not claim.fact_ids:
            return fail("V9", "claim cites no fact", claim.text)
    return ok("V9")


def _terms(text: str) -> list[str]:
    return [term for token in _TOKEN.findall(text) if (term := normalize_term(token))]


def _known_terms(cited: Sequence[Fact], requirement_text: str) -> set[str]:
    texts = [requirement_text]
    for fact in cited:
        texts += [fact.claim, fact.employer or "", fact.role or "", *(t.name for t in fact.tags)]
    return {term for text in texts for term in _terms(text)}


def _looks_like_a_name(token: str, at_sentence_start: bool) -> bool:
    letters = [c for c in token if c.isalpha()]
    if not letters or _ID.match(token.casefold()):
        return False
    if any(c.isdigit() for c in token) or "+" in token or "#" in token:
        return True
    if re.search(r"\w\.\w", token):
        return True
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return True
    if re.search(r"[a-z][A-Z]", token):
        return True
    return token[0].isupper() and not at_sentence_start


def novel_terms(text: str, cited: Sequence[Fact], requirement_text: str) -> list[str]:
    """Terms that look like names, tools or acronyms and are in no cited fact and not in the
    requirement text. First occurrence order, each once. Sentence-initial words are skipped."""
    known = _known_terms(cited, requirement_text)
    found: list[str] = []
    at_start = True
    previous_end = 0
    for match in _TOKEN.finditer(text):
        token = match.group()
        at_start = at_start or "\n" in text[previous_end : match.start()]
        term = normalize_term(token)
        base = term.removesuffix("'s").removesuffix("’s")
        if (
            term
            and base not in known
            and term not in found
            and term not in _COMMON_CAPITALIZED
            and _looks_like_a_name(token.strip(".!?"), at_start)
        ):
            found.append(term)
        at_start = bool(_SENTENCE_END.search(token))
        previous_end = match.end()
    return found


def check_novel_terms(text: str, cited: Sequence[Fact], requirement_text: str) -> Verdict:
    """V10: flag terms in the text that no cited fact or requirement mentions."""
    found = novel_terms(text, cited, requirement_text)
    if found:
        return fail("V10", "text uses a term that no cited fact mentions", found[0])
    return ok("V10")
