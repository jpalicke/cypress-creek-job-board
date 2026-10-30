# ABOUTME: Validator V15: a fact proposed from a resume may only say what its source span says.
# ABOUTME: The span must be in the resume, and its numbers, months, names and tags in the span.
import re
import unicodedata
from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from cypress_creek.scoring.aliases import AliasTable, load_aliases
from cypress_creek.terms import normalize_term
from cypress_creek.validators.claim_words import quantity_words
from cypress_creek.validators.consistency import month_of
from cypress_creek.validators.verdict import Verdict, fail, ok

VALIDATOR_ID = "V15"
VERSION = 1
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_WORD = re.compile(r"[^\W\d_][\w'’+#./-]*")
_MONTH_WORD = re.compile(r"\b[A-Z][a-z]{2,8}\b")
_SPACES = re.compile(r"\s+")
# Capitalised words that are not names: the pronoun a person writes about themselves.
_NOT_NAMES = frozenset({"i"})


class ProposedFact(BaseModel):
    """What the validator needs of a candidate: its claim, its source span and its tag names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    source: str
    tags: list[str] = []


@lru_cache(maxsize=1)
def _aliases() -> AliasTable:
    return load_aliases()


def collapse(text: str) -> str:
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def _numbers(text: str) -> set[str]:
    return {token.rstrip(".,") for token in _NUMBER.findall(text)}


def _months(text: str) -> set[int]:
    return {number for word in _MONTH_WORD.findall(text) if (number := month_of(word))}


def _mentions(text: str, term: str) -> bool:
    """True if the term stands alone in the text, so "c" is not found inside "company"."""
    return re.search(rf"(?<![\w+#]){re.escape(term)}(?![\w+#])", text) is not None


def _folded_words(text: str) -> set[str]:
    return {word.strip(".,;:'’").casefold() for word in _WORD.findall(collapse(text))}


def check_candidate_grounded(resume: str, fact: ProposedFact) -> Verdict:
    """Pass only if the span is in the resume and the claim and tags say nothing beyond it.

    Checked in order: the span, invisible characters, numbers, quantity words, months,
    capitalised names, tags. The first failure is the verdict; the offending text is for logs
    and is never sent to a caller."""
    source = collapse(fact.source)
    if not source or source not in collapse(resume):
        return fail(VALIDATOR_ID, "source_not_in_resume")
    if any(unicodedata.category(char) == "Cf" for char in fact.claim):
        return fail(VALIDATOR_ID, "invisible_character_in_claim")
    claim = collapse(fact.claim)
    for number in sorted(_numbers(claim) - _numbers(source)):
        return fail(VALIDATOR_ID, "number_not_in_source", number)
    for word in sorted(quantity_words(claim) - quantity_words(source)):
        return fail(VALIDATOR_ID, "number_not_in_source", word)
    if _months(claim) - _months(source):
        return fail(VALIDATOR_ID, "month_not_in_source")
    known = _folded_words(source)
    for word in _WORD.findall(claim):
        bare = word.strip(".,;:'’")
        if bare[:1].isupper() and bare.casefold() not in known | _NOT_NAMES:
            return fail(VALIDATOR_ID, "name_not_in_source", bare)
    lowered = unicodedata.normalize("NFKC", source).casefold()
    for tag in fact.tags:
        if not any(
            _mentions(lowered, term) for term in _aliases().terms_for(tag) | {normalize_term(tag)}
        ):
            return fail(VALIDATOR_ID, "tag_not_in_source", tag)
    return ok(VALIDATOR_ID)
