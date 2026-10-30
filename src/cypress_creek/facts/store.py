# ABOUTME: Reads and writes the fact bank file for the browser: add, edit, share, verify, delete.
# ABOUTME: Only verify() sets a verification date, and editing what a fact says takes it away.
import contextlib
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.errors import FactValidationError
from cypress_creek.facts.loader import load_bank, parse_fact
from cypress_creek.facts.models import Evidence, Fact, Kind, Share, Tag

PRIVATE_FILE_MODE = 0o600
# A bank is one small file, so one lock around read, change and replace is enough.
_WRITE_LOCK = threading.Lock()


class FactNotFound(KeyError):
    """No fact has the requested id."""


class FactDraft(BaseModel):
    """What a person types for a fact. There is no id, no verification and no share state here, so
    none of them can be set while saving the text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    kind: Kind
    employer: str | None = None
    issuer: str | None = None
    role: str | None = None
    start: date | None = None
    end: date | None = None
    tags: list[Tag] = []
    evidence: Evidence


class BankStore:
    """The bank file at `path`. A missing file is an empty bank, a corrupt one is kept as is."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def facts(self) -> list[Fact]:
        if not self.path.is_file():
            return []
        return load_bank(self.path).facts

    def get(self, fact_id: str) -> Fact:
        for fact in self.facts():
            if fact.id == fact_id:
                return fact
        raise FactNotFound(fact_id)

    def add(self, draft: FactDraft, *, today: date | None = None) -> Fact:
        with _WRITE_LOCK:
            facts = self.facts()
            fact = _build(
                self._next_id(facts), draft, None, Share.LOCAL_ONLY, today or date.today()
            )
            self._write([*facts, fact], fact.id)
            return fact

    def update(self, fact_id: str, draft: FactDraft, *, today: date | None = None) -> Fact:
        """Replace what the fact says. A change to anything but its share state unverifies it."""
        with _WRITE_LOCK:
            facts = self.facts()
            old = _find(facts, fact_id)
            rebuilt = _build(fact_id, draft, old.verified_on, old.share, today or date.today())
            if _content(rebuilt) != _content(old):
                rebuilt = rebuilt.model_copy(update={"verified_on": None})
            self._write([rebuilt if f.id == fact_id else f for f in facts])
            return rebuilt

    def set_share(self, fact_id: str, share: Share) -> Fact:
        return self._replace(fact_id, {"share": share})

    def verify(self, fact_id: str, *, today: date | None = None) -> Fact:
        """The one place a verification date is set: an explicit call for one fact."""
        return self._replace(fact_id, {"verified_on": today or date.today()})

    def unverify(self, fact_id: str) -> Fact:
        return self._replace(fact_id, {"verified_on": None})

    def delete(self, fact_id: str) -> None:
        with _WRITE_LOCK:
            facts = self.facts()
            _find(facts, fact_id)
            self._write([f for f in facts if f.id != fact_id])

    def _replace(self, fact_id: str, changes: dict[str, Any]) -> Fact:
        with _WRITE_LOCK:
            facts = self.facts()
            changed = _find(facts, fact_id).model_copy(update=changes)
            self._write([changed if f.id == fact_id else f for f in facts])
            return changed

    def _counter(self) -> Path:
        return self.path.with_name(self.path.name + ".next_id")

    def _next_id(self, facts: list[Fact]) -> str:
        """One past every id ever used, so a deleted id never names a different fact later."""
        highest = max((int(f.id[2:]) for f in facts), default=0)
        with contextlib.suppress(OSError, ValueError):
            highest = max(highest, int(self._counter().read_text(encoding="utf-8")) - 1)
        return f"F-{highest + 1:04d}"

    def _write(self, facts: list[Fact], newest: str | None = None) -> None:
        body = yaml.safe_dump(
            {"facts": [f.model_dump(mode="json", exclude_none=True) for f in facts]},
            sort_keys=False,
            allow_unicode=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if newest is not None:
            _atomic(self._counter(), f"{int(newest[2:]) + 1}\n")
        _atomic(self.path, body)


def _find(facts: list[Fact], fact_id: str) -> Fact:
    for fact in facts:
        if fact.id == fact_id:
            return fact
    raise FactNotFound(fact_id)


def _content(fact: Fact) -> dict[str, Any]:
    return fact.model_dump(mode="json", exclude={"id", "verified_on", "share"})


def _build(
    fact_id: str, draft: FactDraft, verified_on: date | None, share: Share, today: date
) -> Fact:
    """Validate with the same rules the loader uses, so the file always loads again."""
    raw: dict[str, Any] = {
        "id": fact_id,
        **draft.model_dump(mode="json", exclude_none=True),
        "share": share.value,
    }
    if verified_on is not None:
        raw["verified_on"] = verified_on.isoformat()
    try:
        return parse_fact(raw, 0, strict=False, today=today)
    except FactValidationError as error:
        raise FactValidationError(fact_id, error.field, error.reason) from None


def _atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)
