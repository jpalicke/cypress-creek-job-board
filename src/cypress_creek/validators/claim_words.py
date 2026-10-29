# ABOUTME: Small deterministic word lists for claims a sentence can add: quantity, impact, rank.
# ABOUTME: Also negation. Words map to categories, so "doubling" matches a fact saying "doubled".
import re
from collections.abc import Callable, Iterable

from cypress_creek.facts.models import Fact

# Words with hyphens or apostrophes stay whole, so "double-checked" is not "double".
_WORD = re.compile(r"[a-z]+(?:['’-][a-z]+)*")

NEGATION = "negation"

_QUANTITY: dict[str, re.Pattern[str]] = {
    "decade": re.compile(r"decades?"),
    "dozen": re.compile(r"dozens?"),
    "couple": re.compile(r"couples?"),
    "half": re.compile(r"half"),
    "double": re.compile(r"doubl(?:e|es|ed|ing)"),
    "triple": re.compile(r"tripl(?:e|es|ed|ing)"),
    "quadruple": re.compile(r"quadrupl(?:e|es|ed|ing)"),
    "hundreds": re.compile(r"hundreds"),
    "thousands": re.compile(r"thousands"),
    "millions": re.compile(r"millions"),
    "billions": re.compile(r"billions"),
    "numerous": re.compile(r"numerous"),
}

# Results a sentence can claim. Grouped so that a paraphrase of a fact ("cut" for "reduced")
# stays inside the fact's own group, while a result no fact mentions is flagged.
_IMPACT: dict[str, re.Pattern[str]] = {
    "reduce": re.compile(
        r"reduc\w*|decreas\w*|cut|cuts|cutting|lowered|lowering|shorten\w*|trimm?(?:ed|ing)"
        r"|slash\w*"
    ),
    "increase": re.compile(r"increas\w*|grew|grow\w*|boost\w*|expand\w*"),
    "improve": re.compile(r"improv\w*|enhanc\w*|optimi[sz]\w*|streamlin\w*"),
    "double": _QUANTITY["double"],
    "triple": _QUANTITY["triple"],
    "quadruple": _QUANTITY["quadruple"],
    "save": re.compile(r"save|saves|saved|saving|savings"),
    "revenue": re.compile(r"revenues?|profit\w*|sales"),
    "cost": re.compile(r"costs?|costing|budget\w*"),
    "speed": re.compile(r"faster|fastest|quicker|quickest|speedup|speed|speeded|accelerat\w*"),
    "award": re.compile(r"awards?|awarded|won|winning|prizes?"),
}

_SENIORITY = frozenset(
    {
        "senior",
        "staff",
        "principal",
        "chief",
        "director",
        "executive",
        "architect",
        "expert",
        "sole",
        "solely",
        "single-handedly",
        "world-class",
        "award-winning",
        "large-scale",
        "mission-critical",
        "company-wide",
        "org-wide",
        "global",
        "vp",
    }
)

_NEGATION = re.compile(
    r"never|not|no|none|nor|neither|without|cannot|unable|except|lack\w*|fail\w*"
    r"|\w+n['’]t"
)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _matches(text: str, table: dict[str, re.Pattern[str]]) -> set[str]:
    found: set[str] = set()
    for word in _words(text):
        for name, pattern in table.items():
            if pattern.fullmatch(word):
                found.add(name)
    return found


def quantity_words(text: str) -> set[str]:
    """Words that state an amount without a digit, such as decade, dozen, half or doubling."""
    return _matches(text, _QUANTITY)


def impact_words(text: str) -> set[str]:
    """Words that claim a result, such as reduced, increased, saved, revenue or won."""
    return _matches(text, _IMPACT)


def seniority_words(text: str) -> set[str]:
    """Words that claim rank or scope, such as senior, principal, sole or large-scale."""
    return {word for word in _words(text) if word in _SENIORITY}


def negation_words(text: str) -> set[str]:
    """{"negation"} when the text negates something with never, not, no, without and the like."""
    return {NEGATION} if any(_NEGATION.fullmatch(word) for word in _words(text)) else set()


def fact_text(fact: Fact) -> str:
    """Every word of a fact a sentence may repeat: claim, names, tags and their levels."""
    parts = [fact.claim, fact.employer or "", fact.role or "", fact.issuer or ""]
    parts += [part for tag in fact.tags for part in (tag.name, tag.level.value)]
    return " ".join(parts)


def known_in(texts: Iterable[str], finder: Callable[[str], set[str]]) -> set[str]:
    """Union of a finder's matches over several texts."""
    found: set[str] = set()
    for text in texts:
        found |= finder(text)
    return found
