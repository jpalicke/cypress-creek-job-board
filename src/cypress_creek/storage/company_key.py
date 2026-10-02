# ABOUTME: company_key, the one function every company name comparison goes through.
# ABOUTME: Folds case, accents, Unicode confusables, punctuation, spacing and legal suffixes.
import unicodedata
from functools import cache
from pathlib import Path

DEFAULT_CONFUSABLES_PATH = Path(__file__).resolve().parents[3] / "config" / "confusables.txt"
MAX_NAME_LENGTH = 1000
# Confusable targets can themselves be confusable (a percent sign folds to a zero, a zero to o).
# The fold is applied this many times, and a test checks every character in the shipped data
# is stable by then.
FOLD_PASSES = 8
# Dropped without splitting a word, so "L.L.C." and "O'Reilly" stay whole.
JOINING_PUNCTUATION = frozenset(".'’")

# Every addition needs a row in tests/unit/test_company_key.py (each suffix is tested).
LEGAL_SUFFIXES = frozenset(
    {"inc", "incorporated", "llc", "llp", "ltd", "limited", "corp", "corporation", "gmbh", "plc"}
)


class CompanyNameError(ValueError):
    """The name cannot produce a key: empty, punctuation only or too long."""


class ConfusablesError(Exception):
    """The homoglyph table is missing, malformed or ambiguous."""


def load_confusables(path: Path = DEFAULT_CONFUSABLES_PATH) -> dict[str, str]:
    """Read the Unicode confusables data (UTS 39 format) into source character -> skeleton."""
    if not path.is_file():
        raise ConfusablesError(f"confusables data not found: {path}")
    table: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = [field.strip() for field in line.split(";")]
        if len(fields) != 3:
            raise ConfusablesError(f"line {number}: expected 'source ; target ; type'")
        try:
            sources = [chr(int(code, 16)) for code in fields[0].split()]
            target = "".join(chr(int(code, 16)) for code in fields[1].split())
        except (ValueError, OverflowError) as error:
            raise ConfusablesError(f"line {number}: invalid code point") from error
        if len(sources) != 1 or not target:
            raise ConfusablesError(f"line {number}: needs one source and a non empty target")
        if table.setdefault(sources[0], target) != target:
            raise ConfusablesError(f"line {number}: {fields[0]} is listed twice")
    if not table:
        raise ConfusablesError("confusables data has no entries")
    return table


@cache
def _confusables() -> dict[str, str]:
    return load_confusables()


def _fold(name: str) -> list[str]:
    """Words made only of letters and digits: accents, case and homoglyphs folded away."""
    table = _confusables()
    skeleton = unicodedata.normalize("NFKD", name).casefold()
    for _ in range(FOLD_PASSES):
        mapped = "".join(table.get(char, char) for char in skeleton)
        skeleton = unicodedata.normalize("NFKD", mapped).casefold()
    words: list[str] = []
    word: list[str] = []
    for char in skeleton:
        category = unicodedata.category(char)
        if category[0] in "LN":
            word.append("l" if char == "i" else char)
        elif category in ("Mn", "Cf") or char in JOINING_PUNCTUATION:
            continue
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return words


@cache
def _suffix_keys() -> frozenset[str]:
    """Legal suffixes in key space, since folding rewrites letters such as i."""
    return frozenset("".join(_fold(suffix)) for suffix in LEGAL_SUFFIXES)


def company_key(name: str) -> str:
    """The comparison key for a company name. Raises CompanyNameError when none can be made."""
    if len(name) > MAX_NAME_LENGTH:
        raise CompanyNameError(f"company name too long ({len(name)} characters)")
    words = _fold(name)
    while len(words) > 1 and words[-1] in _suffix_keys():
        words.pop()
    key = unicodedata.normalize("NFKC", "".join(words))
    if not key:
        raise CompanyNameError("company name has no letters or digits")
    return key
