# ABOUTME: Tests term normalization and the alias table that maps requirement terms to bank tags.
# ABOUTME: The table is data in config/aliases.yaml, never hard coded in Python.
from pathlib import Path

import pytest

from cypress_creek.facts.models import Tag
from cypress_creek.scoring.aliases import (
    DEFAULT_ALIASES_PATH,
    AliasTable,
    AliasTableError,
    load_aliases,
)
from cypress_creek.terms import normalize_term

TABLE = AliasTable({"postgresql": ["postgres", "psql"], "javascript": ["js", "ecmascript"]})


def test_alias_resolves_to_the_canonical_tag() -> None:
    assert TABLE.resolve("postgres") == "postgresql"


def test_canonical_name_resolves_to_itself() -> None:
    assert TABLE.resolve("PostgreSQL") == "postgresql"


def test_unknown_term_resolves_to_none() -> None:
    assert TABLE.resolve("cobol") is None


def test_canonical_form_falls_back_to_the_normalized_term() -> None:
    assert TABLE.canonical("  COBOL. ") == "cobol"
    assert TABLE.canonical("JS") == "javascript"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Python  ", "python"),
        ("PYTHON,", "python"),
        ("Ｐython", "python"),
        ("C++", "c++"),
        ("C#", "c#"),
        (".NET", ".net"),
        ("Node.js", "node.js"),
        ("machine   learning", "machine learning"),
        ("(SQL)", "sql"),
        ("Straße", "strasse"),
    ],
)
def test_normalize_term(raw: str, expected: str) -> None:
    assert normalize_term(raw) == expected


def test_tag_names_are_normalized_by_the_same_function() -> None:
    assert Tag(name=" PostgreSQL ", level="expert").name == "postgresql"  # type: ignore[arg-type]


def test_alias_listed_under_two_tags_is_rejected() -> None:
    with pytest.raises(AliasTableError, match="postgres"):
        AliasTable({"postgresql": ["postgres"], "postgres-xl": ["postgres"]})


def test_alias_equal_to_another_canonical_tag_is_rejected() -> None:
    with pytest.raises(AliasTableError, match="java"):
        AliasTable({"java": [], "javascript": ["java"]})


def test_aliases_are_loaded_from_a_yaml_file(tmp_path: Path) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text("aliases:\n  postgresql: [postgres]\n", encoding="utf8")
    assert load_aliases(path).resolve("postgres") == "postgresql"


@pytest.mark.parametrize(
    "text", ["", "aliases: [a, b]\n", "aliases:\n  x: notalist\n", "other: 1\n"]
)
def test_bad_alias_files_are_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text(text, encoding="utf8")
    with pytest.raises(AliasTableError):
        load_aliases(path)


def test_missing_alias_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AliasTableError, match="not found"):
        load_aliases(tmp_path / "nope.yaml")


def test_shipped_default_table_loads_and_maps_postgres() -> None:
    assert DEFAULT_ALIASES_PATH.name == "aliases.yaml"
    assert load_aliases(DEFAULT_ALIASES_PATH).resolve("postgres") == "postgresql"
