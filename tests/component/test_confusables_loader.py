# ABOUTME: Tests loading the homoglyph table from config/confusables.yaml, real and bad files.
# ABOUTME: Every shipped entry must fold a non Latin character onto one ASCII letter or digit.
from pathlib import Path

import pytest

from cypress_creek.storage.company_key import (
    DEFAULT_CONFUSABLES_PATH,
    ConfusablesError,
    load_confusables,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "confusables.yaml"
    path.write_text(text, encoding="utf8")
    return path


def test_the_shipped_table_folds_non_latin_characters_to_ascii() -> None:
    table = load_confusables(DEFAULT_CONFUSABLES_PATH)
    assert table["\u0430"] == "a"
    assert table["\u03bf"] == "o"
    for variant, letter in table.items():
        assert not variant.isascii()
        assert letter.isascii()
        assert letter.isalnum()


def test_a_custom_table_is_loaded(tmp_path: Path) -> None:
    path = write(tmp_path, 'confusables:\n  a: ["\\u0430", "\\u0251"]\n')
    assert load_confusables(path) == {"\u0430": "a", "\u0251": "a"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("other: 1\n", "top level 'confusables' mapping"),
        ("confusables: [a]\n", "top level 'confusables' mapping"),
        ("confusables: {a: x}\n", "must be a list"),
        ('confusables: {ab: ["\\u0430"]}\n', "single ASCII letter or digit"),
        ('confusables: {"!": ["\\u0430"]}\n', "single ASCII letter or digit"),
        ('confusables: {a: ["\\u0430\\u0430"]}\n', "single character"),
        ('confusables: {a: ["b"]}\n', "must not be ASCII"),
        ('confusables: {a: ["\\u0430"], b: ["\\u0430"]}\n', "listed under both"),
        ("confusables: {a: [}\n", "invalid YAML"),
    ],
)
def test_bad_tables_are_refused(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfusablesError, match=message):
        load_confusables(write(tmp_path, text))


def test_a_missing_table_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfusablesError, match="not found"):
        load_confusables(tmp_path / "nope.yaml")
