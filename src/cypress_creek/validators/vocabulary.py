# ABOUTME: The closed vocabulary for draft sentences: every word must come from a cited fact.
# ABOUTME: One reviewed list of function words and one small inflection rule, both in this file.
import re
import unicodedata
from collections.abc import Iterable

from cypress_creek.validators.consistency import extract_numbers

# The only words a draft may use without a cited fact saying them. Each one is a connective that
# carries no claim of its own. Words that can carry a claim (no, not, never, only, first, more,
# most, all, every, many, over, or, but) are deliberately not here. Adding a word needs a reviewer.
FUNCTION_WORDS = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "on", "at", "for", "with", "and", "by", "as",
        "from", "using", "while", "its", "their", "into", "that", "which", "who", "was",
        "were", "is", "are", "been", "it", "this", "these", "those", "through", "via",
    }
)  # fmt: skip

# Month names are read by V7 together with the year, so they are not a vocabulary question.
MONTH_WORDS = frozenset(
    {
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
    }
)  # fmt: skip

# A token is a run of letters, with one inner apostrophe for a possessive or a contraction.
# Hyphens split a compound, so "double-checked" needs both words. Digits are V8's concern.
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_CITATION = re.compile(r"\b[fr]-\d+\b", re.IGNORECASE)
_SUFFIXES = ("ies", "ing", "ed", "es", "s")
_MIN_STEM = 3


def normalize(text: str) -> str:
    """NFKC, no format characters (zero width and soft hyphen), lower case. The same text a
    person would read, so a look-alike or an invisible character cannot hide a word."""
    folded = unicodedata.normalize("NFKC", text)
    visible = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return visible.casefold()


def stem(word: str) -> str:
    """A small inflection rule: drop one of ies, ing, ed, es, s, then a final e and a doubled
    final consonant. "migrating", "migrated" and "migrate" agree, "manager" and "manage" do not."""
    base = word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            base = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    if base.endswith("e") and len(base) > _MIN_STEM:
        base = base[:-1]
    if len(base) > _MIN_STEM and base[-1] == base[-2] and base[-1] not in "aeiou":
        base = base[:-1]
    return base


def _tokens(text: str) -> list[str]:
    cleaned = _CITATION.sub(" ", normalize(text))
    words = []
    for token in _WORD.findall(cleaned):
        words.append(re.sub(r"['’]s$", "", token))
    return words


def vocabulary_words(texts: Iterable[str]) -> set[str]:
    """The stems of every word in the given texts."""
    return {stem(word) for text in texts for word in _tokens(text)}


def _is_free(word: str) -> bool:
    return word in FUNCTION_WORDS or word in MONTH_WORDS or bool(extract_numbers(word))


def unknown_words(text: str, allowed_texts: Iterable[str]) -> list[str]:
    """Words of the text that no allowed text uses, in order, each once. Function words, month
    names and numbers (digits or words) are free. Matching is by stem."""
    known = vocabulary_words(allowed_texts)
    found: list[str] = []
    for word in _tokens(text):
        if not _is_free(word) and stem(word) not in known and word not in found:
            found.append(word)
    return found


def unknown_characters(text: str, allowed_texts: Iterable[str]) -> set[str]:
    """Non-ASCII characters of the raw text that no allowed text has: look-alike letters, full
    width forms, zero width and other invisible characters. A draft may only be plain ASCII
    unless a cited fact itself uses the character, so what a person copies is what was checked."""
    allowed = {ch for allowed_text in allowed_texts for ch in allowed_text}
    return {ch for ch in text if not ch.isascii() and ch not in allowed}
