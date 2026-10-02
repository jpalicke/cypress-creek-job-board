# ABOUTME: Loads and validates the fact bank from YAML, refusing hostile YAML and bad data.
# ABOUTME: Strict mode (used by evals) also requires every fact to be verified.
import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cypress_creek.facts.dates import date_problems
from cypress_creek.facts.errors import BankLoadError, FactValidationError
from cypress_creek.facts.models import Bank, Fact

BANK_PATH_ENV = "CYPRESS_CREEK_BANK"
DEFAULT_BANK_PATH = Path("facts.private") / "bank.yaml"
MAX_BANK_BYTES = 1_000_000


def parse_fact(raw: Mapping[str, Any], position: int, *, strict: bool, today: date) -> Fact:
    fact_id = str(raw.get("id") or f"facts[{position}]")
    try:
        fact = Fact.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        raise FactValidationError(fact_id, str(first["loc"][0]), first["msg"]) from error
    if strict and fact.verified_on is None:
        raise FactValidationError(fact_id, "verified_on", "required in strict mode")
    for field, reason in date_problems(fact.start, fact.end, fact.verified_on, today):
        raise FactValidationError(fact_id, field, reason)
    return fact


def parse_bank(data: Mapping[str, Any], *, strict: bool = False, today: date | None = None) -> Bank:
    today = today or date.today()
    raw_facts = data.get("facts")
    if not isinstance(raw_facts, list):
        raise BankLoadError("bank must contain a 'facts' list")
    facts: list[Fact] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_facts):
        if not isinstance(raw, Mapping):
            raise BankLoadError(f"facts[{position}] must be a mapping")
        fact = parse_fact(raw, position, strict=strict, today=today)
        if fact.id in seen:
            raise FactValidationError(fact.id, "id", "duplicate id")
        seen.add(fact.id)
        facts.append(fact)
    return Bank(facts=facts)


def bank_path() -> Path:
    return Path(os.environ.get(BANK_PATH_ENV, DEFAULT_BANK_PATH))


def safe_load_yaml(text: str) -> Any:
    """Safe YAML load that also refuses anchors and aliases, which enable expansion attacks."""
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
                raise BankLoadError("YAML anchors and aliases are not allowed in a bank")
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise BankLoadError(f"invalid YAML: {error}") from error


def load_bank(path: Path | None = None, *, strict: bool = False) -> Bank:
    path = path or bank_path()
    if not path.is_file():
        raise BankLoadError(f"bank file not found: {path}")
    if path.stat().st_size > MAX_BANK_BYTES:
        raise BankLoadError(f"bank file too large (limit {MAX_BANK_BYTES} bytes): {path}")
    data = safe_load_yaml(path.read_text(encoding="utf8"))
    if not isinstance(data, Mapping):
        raise BankLoadError("bank must be a mapping with a 'facts' list")
    return parse_bank(data, strict=strict)
