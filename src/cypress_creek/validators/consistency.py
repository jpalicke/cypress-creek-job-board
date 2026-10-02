# ABOUTME: Validators V7 entity consistency and V8 numeric consistency for generated text.
# ABOUTME: Dates, employers, roles and numbers in the output must come from the cited facts.
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from cypress_creek.facts.models import Bank, Fact, Kind
from cypress_creek.terms import normalize_term
from cypress_creek.validators.verdict import Verdict, fail, ok

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))

# A date token, tried in this order so "2019-03-01" is not read as a year and a month.
_DATE = re.compile(
    rf"(?P<iso_day>\b(?:19|20)\d{{2}}-\d{{2}}-\d{{2}}\b)"
    rf"|(?P<iso_month>\b(?:19|20)\d{{2}}-\d{{2}}\b)"
    rf"|(?P<named>\b(?:{_MONTH_NAMES})\.?\s+(?:19|20)\d{{2}}\b)"
    rf"|(?P<year>\b(?:19|20)\d{{2}}\b)",
    re.IGNORECASE,
)
_FACT_OR_REQUIREMENT_ID = re.compile(r"\b[FR]-\d+\b")


def _fact_dates(fact: Fact) -> set[tuple[int, int | None, int | None]]:
    """Every (year, month, day) form of a date a fact may be quoted as."""
    allowed: set[tuple[int, int | None, int | None]] = set()
    for moment in (fact.start, fact.end):
        if moment is not None:
            allowed |= {
                (moment.year, None, None),
                (moment.year, moment.month, None),
                (moment.year, moment.month, moment.day),
            }
    return allowed


def _date_parts(match: re.Match[str]) -> tuple[int, int | None, int | None] | None:
    """The parts a date token names, or None when it is not a real date."""
    token = match.group().casefold()
    if match.lastgroup == "year":
        return int(token), None, None
    if match.lastgroup == "named":
        word, year = token.rstrip().rsplit(None, 1)
        return int(year), _MONTHS[word.rstrip(".")], None
    parts = [int(piece) for piece in token.split("-")]
    try:
        date(parts[0], parts[1], parts[2] if len(parts) == 3 else 1)
    except ValueError:
        return None
    return parts[0], parts[1], parts[2] if len(parts) == 3 else None


def _name_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")


def _entity_names(fact: Fact) -> set[str]:
    names = {fact.employer, fact.role}
    if fact.kind in (Kind.CERTIFICATION, Kind.EDUCATION):
        names |= {tag.name for tag in fact.tags} | {fact.issuer}
    return {normalize_term(name) for name in names if name and normalize_term(name)}


def check_entities(text: str, cited: Sequence[Fact], bank: Bank) -> Verdict:
    """V7: dates match a cited fact, and no employer, role, certification or school of an
    uncited bank fact appears. Invented names that are in no fact are V10's concern."""
    allowed_dates = set().union(*(_fact_dates(fact) for fact in cited))
    for match in _DATE.finditer(text):
        parts = _date_parts(match)
        if parts is not None and parts not in allowed_dates:
            return fail("V7", "date does not match any cited fact", match.group())

    cited_ids = {fact.id for fact in cited}
    cited_names = sorted(
        {name for fact in cited for name in _entity_names(fact)}, key=len, reverse=True
    )
    remaining = normalize_term(text)
    for name in cited_names:
        remaining = _name_pattern(name).sub(" ", remaining)
    for fact in bank.facts:
        if fact.id in cited_ids:
            continue
        for name in sorted(_entity_names(fact) - set(cited_names)):
            if _name_pattern(name).search(remaining):
                return fail("V7", "names an entity of a fact that was not cited", name)
    return ok("V7")


_UNITS = {
    word: value
    for value, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_TENS = {
    word: value * 10
    for value, word in enumerate(
        ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"], start=2
    )
}
_MULTIPLIERS = {"thousand": 1_000, "million": 1_000_000}
_NUMBER_WORDS = {*_UNITS, *_TENS, *_MULTIPLIERS, "hundred"}

_DIGITS = re.compile(r"(?<![A-Za-z0-9_.,])(-?)(\d+(?:,\d{3})*(?:\.\d+)?)")
_WORD = re.compile(r"[A-Za-z]+")
_WORD_GAP = re.compile(r"[\s-]+")


def _canonical(number: str) -> str:
    value = Decimal(number.replace(",", ""))
    return str(int(value)) if value == value.to_integral_value() else format(value.normalize(), "f")


def _word_value(words: list[str]) -> int:
    total = current = 0
    for word in words:
        if word == "hundred":
            current = max(current, 1) * 100
        elif word in _MULTIPLIERS:
            total += max(current, 1) * _MULTIPLIERS[word]
            current = 0
        else:
            current += _UNITS.get(word, _TENS.get(word, 0))
    return total + current


def _word_numbers(text: str) -> list[tuple[int, str]]:
    """Runs of adjacent number words, such as "twenty-three" or "two hundred fifty". A lone
    "one" is skipped because it is far more often a pronoun than a count."""
    found: list[tuple[int, str]] = []
    run: list[re.Match[str]] = []

    def close() -> None:
        words = [piece.group() for piece in run]
        if run and words != ["one"]:
            found.append((run[0].start(), str(_word_value(words))))
        run.clear()

    for match in _WORD.finditer(text.casefold()):
        if match.group() not in _NUMBER_WORDS:
            close()
        else:
            if run and not _WORD_GAP.fullmatch(text[run[-1].end() : match.start()]):
                close()
            run.append(match)
    close()
    return found


def extract_numbers(text: str) -> list[str]:
    """Canonical numbers in text, in order, from digits and number words. Fact and requirement
    IDs are ignored, so are tokens like "k8s" where digits are part of a name."""
    text = _FACT_OR_REQUIREMENT_ID.sub(" ", text)
    found = [(m.start(), _canonical(m.group(1) + m.group(2))) for m in _DIGITS.finditer(text)]
    found += _word_numbers(text)
    return [number for _, number in sorted(found)]


def _strip_iso_dates(text: str) -> str:
    return _DATE.sub(lambda m: " " if m.lastgroup in ("iso_day", "iso_month") else m.group(), text)


def _fact_numbers(fact: Fact) -> set[str]:
    texts = [
        fact.claim,
        fact.employer or "",
        fact.role or "",
        fact.issuer or "",
        *(tag.name for tag in fact.tags),
    ]
    numbers = {number for text in texts for number in extract_numbers(text)}
    return numbers | {str(moment.year) for moment in (fact.start, fact.end) if moment is not None}


def check_numbers(text: str, cited: Sequence[Fact], requirement_text: str) -> Verdict:
    """V8: every number in the text appears in a cited fact (claim, names, date years) or in the
    requirement text it answers. The parts of ISO dates are V7's concern."""
    allowed = set(extract_numbers(requirement_text))
    for fact in cited:
        allowed |= _fact_numbers(fact)
    for number in extract_numbers(_strip_iso_dates(text)):
        if number not in allowed:
            return fail("V8", "number does not appear in any cited fact", number)
    return ok("V8")
