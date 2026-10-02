# ABOUTME: Loads and validates the tag alias table, which is data in config/aliases.yaml.
# ABOUTME: Maps requirement terms onto the canonical tag names used in the fact bank.
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from cypress_creek.terms import normalize_term

DEFAULT_ALIASES_PATH = Path(__file__).resolve().parents[3] / "config" / "aliases.yaml"


class AliasTableError(Exception):
    """The alias table is missing, malformed or ambiguous."""


class AliasTable:
    def __init__(self, aliases: Mapping[str, Sequence[str]]) -> None:
        self._canonical_by_term: dict[str, str] = {}
        canonicals = {normalize_term(name) for name in aliases}
        for name, alias_list in aliases.items():
            canonical = normalize_term(name)
            self._canonical_by_term[canonical] = canonical
            for alias in alias_list:
                term = normalize_term(alias)
                if term in canonicals and term != canonical:
                    raise AliasTableError(f"alias {term!r} is also a canonical tag")
                existing = self._canonical_by_term.get(term)
                if existing is not None and existing != canonical:
                    raise AliasTableError(
                        f"alias {term!r} is listed under both {existing!r} and {canonical!r}"
                    )
                self._canonical_by_term[term] = canonical

    def resolve(self, term: str) -> str | None:
        """Canonical tag for a term or alias, or None when the table does not know it."""
        return self._canonical_by_term.get(normalize_term(term))

    def canonical(self, term: str) -> str:
        """Canonical tag when known, otherwise the normalized term itself."""
        return self.resolve(term) or normalize_term(term)


def load_aliases(path: Path = DEFAULT_ALIASES_PATH) -> AliasTable:
    if not path.is_file():
        raise AliasTableError(f"alias table not found: {path}")
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf8"))
    except yaml.YAMLError as error:
        raise AliasTableError(f"invalid YAML in alias table: {error}") from error
    if not isinstance(data, Mapping) or not isinstance(data.get("aliases"), Mapping):
        raise AliasTableError("alias table needs a top level 'aliases' mapping")
    table: dict[str, list[str]] = {}
    for name, alias_list in data["aliases"].items():
        if not isinstance(alias_list, list) or not all(isinstance(a, str) for a in alias_list):
            raise AliasTableError(f"aliases for {name!r} must be a list of strings")
        table[str(name)] = alias_list
    return AliasTable(table)
