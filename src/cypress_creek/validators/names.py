# ABOUTME: Validator V14 shape check for model-suggested company names.
# ABOUTME: Only plain names pass, so URLs, slugs and injected text cannot ride along.
import re
import unicodedata

from cypress_creek.validators.verdict import Verdict, fail, ok

MIN_LENGTH = 2
MAX_LENGTH = 60
MAX_WORDS = 6

_PUNCTUATION = frozenset("&.'-,’ ")
_TLD_LIKE = re.compile(r"\.[A-Za-z]{2,}")


def _script(letter: str) -> str:
    return unicodedata.name(letter, "UNKNOWN").split()[0]


def _problem(name: str) -> str | None:
    if not MIN_LENGTH <= len(name) <= MAX_LENGTH:
        return f"length is not {MIN_LENGTH} to {MAX_LENGTH}"
    if len(name.split()) > MAX_WORDS:
        return f"more than {MAX_WORDS} words"
    for character in name:
        if unicodedata.category(character)[0] not in "LN" and character not in _PUNCTUATION:
            return "contains a character a company name does not need"
    if _TLD_LIKE.search(name):
        return "looks like a web address"
    if " " not in name and "-" in name and name == name.lower():
        return "looks like a slug"
    if name.isdigit():
        return "is only digits"
    if len({_script(c) for c in name if c.isalpha()}) > 1:
        return "mixes scripts"
    return None


def check_company_name(name: str) -> Verdict:
    """V14: a suggested company name is short plain text with no URL, slug or free text."""
    normalized = unicodedata.normalize("NFKC", name).strip()
    problem = _problem(normalized)
    if problem is not None:
        return fail("V14", f"company name {problem}", name)
    return ok("V14")
