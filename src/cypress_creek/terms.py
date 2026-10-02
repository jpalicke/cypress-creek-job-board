# ABOUTME: Term normalization shared by the fact bank loader and the alias table.
# ABOUTME: One function so a bank tag and a posting term compare under the same rules.
import re
import unicodedata

# Characters trimmed from either end. A trailing dot is trimmed too, a leading dot is kept
# so that ".net" survives, and "+" and "#" are never trimmed so "c++" and "c#" survive.
_EDGE_PUNCTUATION = ",;:!?()[]{}\"'“”‘’"
_WHITESPACE = re.compile(r"\s+")


def normalize_term(term: str) -> str:
    folded = unicodedata.normalize("NFKC", term).casefold()
    collapsed = _WHITESPACE.sub(" ", folded).strip()
    return collapsed.strip(_EDGE_PUNCTUATION + " ").rstrip(". ").strip(_EDGE_PUNCTUATION + " ")
