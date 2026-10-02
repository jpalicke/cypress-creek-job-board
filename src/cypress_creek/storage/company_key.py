# ABOUTME: company_key, the one function every company name comparison goes through.
# ABOUTME: Folds case, accents, homoglyphs, punctuation, spacing and legal suffixes to one key.
import unicodedata
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFUSABLES_PATH = Path(__file__).resolve().parents[3] / "config" / "confusables.yaml"
MAX_NAME_LENGTH = 1000
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
    """Map each lookalike character to the ASCII letter or digit it imitates."""
    if not path.is_file():
        raise ConfusablesError(f"confusables table not found: {path}")
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf8"))
    except yaml.YAMLError as error:
        raise ConfusablesError(f"invalid YAML in confusables table: {error}") from error
    if not isinstance(data, Mapping) or not isinstance(data.get("confusables"), Mapping):
        raise ConfusablesError("confusables table needs a top level 'confusables' mapping")
    table: dict[str, str] = {}
    for letter, variants in data["confusables"].items():
        if not (
            isinstance(letter, str) and len(letter) == 1 and letter.isascii() and letter.isalnum()
        ):
            raise ConfusablesError(f"{letter!r} must be a single ASCII letter or digit")
        if not (isinstance(variants, list) and all(isinstance(v, str) for v in variants)):
            raise ConfusablesError(f"variants for {letter!r} must be a list of strings")
        for variant in variants:
            if len(variant) != 1:
                raise ConfusablesError(f"{variant!r} under {letter!r} must be a single character")
            if variant.isascii():
                raise ConfusablesError(f"{variant!r} under {letter!r} must not be ASCII")
            if table.setdefault(variant, letter) != letter:
                raise ConfusablesError(
                    f"{variant!r} is listed under both {table[variant]!r} and {letter!r}"
                )
    return table


@cache
def _confusables() -> dict[str, str]:
    return load_confusables()


def _fold(name: str) -> list[str]:
    """Words made only of letters and digits: accents, case and homoglyphs folded away."""
    table = _confusables()
    words: list[str] = []
    word: list[str] = []
    for char in unicodedata.normalize("NFKD", name).casefold():
        char = table.get(char, char)
        category = unicodedata.category(char)
        if category[0] in "LN":
            word.append(char)
        elif category in ("Mn", "Cf") or char in JOINING_PUNCTUATION:
            continue
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return words


def company_key(name: str) -> str:
    """The comparison key for a company name. Raises CompanyNameError when none can be made."""
    if len(name) > MAX_NAME_LENGTH:
        raise CompanyNameError(f"company name too long ({len(name)} characters)")
    words = _fold(name)
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    key = unicodedata.normalize("NFKC", "".join(words))
    if not key:
        raise CompanyNameError("company name has no letters or digits")
    return key
