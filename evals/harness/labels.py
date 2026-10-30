# ABOUTME: The hand label schema for posting fixtures and the validator that checks a label file.
# ABOUTME: Spans must be exact posting text. Fact references must be real, verified and shareable.
import re
import subprocess
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from cypress_creek.facts import Bank
from cypress_creek.facts.models import Share, clean_issuer
from cypress_creek.ingest.models import Importance, RequirementKind
from cypress_creek.scoring.support import Support
from cypress_creek.terms import normalize_term
from cypress_creek.validators.cues import has_cue, is_importance_heading, split_sentences

MAX_LABEL_BYTES = 200_000


class LabelError(Exception):
    """A label file is malformed or disagrees with its posting or the bank."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class LabelsNotCommitted(Exception):
    """A case may not run until its label file is committed and unchanged."""


class Status(StrEnum):
    SUPPORTED = "supported"
    GAP = "gap"


class CueExpectation(StrEnum):
    COVERED = "covered"
    NOT_A_REQUIREMENT = "not_a_requirement"


class Provenance(BaseModel):
    """Who wrote the labels and under what authority. Review stays pending until Joe P signs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    labeled_by: str = Field(min_length=1)
    review: Literal["pending", "reviewed"]
    labeled_on: date
    model_output_used: Literal[False]


class LabeledRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^L-\d+$")
    span: str = Field(min_length=1)
    kind: RequirementKind
    term: str
    years: int | None = Field(default=None, ge=1)
    issuer: str | None = None
    importance: Importance
    expected_support: Support
    expected_status: Status
    fact_ids: list[str] = []
    planted_gap: str | None = None
    note: str | None = None

    @field_validator("term")
    @classmethod
    def _normalize_term(cls, value: str) -> str:
        normalized = normalize_term(value)
        if not normalized:
            raise ValueError("term is empty after normalization")
        return normalized

    @field_validator("issuer")
    @classmethod
    def _clean_issuer(cls, value: str | None) -> str | None:
        return clean_issuer(value)


class CueSentence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    span: str = Field(min_length=1)
    expected: CueExpectation
    note: str | None = None


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str = Field(min_length=1)
    provenance: Provenance
    requirements: list[LabeledRequirement] = Field(min_length=1)
    cue_sentences: list[CueSentence] = []


def _describe(error: ValidationError) -> list[str]:
    """Field paths and rule messages only, never the submitted values."""
    problems = []
    for item in error.errors(include_input=False, include_url=False, include_context=False):
        where = ".".join(str(part) for part in item["loc"])
        problems.append(f"{where}: {item['msg']}" if where else item["msg"])
    return problems


def parse_labels(data: Any) -> Labels:
    try:
        return Labels.model_validate(data)
    except ValidationError as error:
        raise LabelError(_describe(error)) from None


def load_labels(path: Path) -> Labels:
    if path.stat().st_size > MAX_LABEL_BYTES:
        raise LabelError([f"{path.name}: file is larger than {MAX_LABEL_BYTES} bytes"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        raise LabelError([f"{path.name}: not readable as YAML text"]) from None
    return parse_labels(data)


_ROW = re.compile(r"^\|(.+)\|\s*$")


def planted_gap_key(kind: str, term: str, years: int | None, issuer: str | None) -> str:
    key = f"{kind}:{normalize_term(term)}"
    if years is not None:
        key += f":{years}"
    if issuer:
        key += f"@{issuer.strip().casefold()}"
    return key


def planted_gap_support(path: Path) -> dict[str, Support]:
    """Read the PLANTED_GAPS.md table into {key: support}, keyed by kind, term, years, issuer."""
    rows: dict[str, Support] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(1).split("|")]
        if len(cells) < 5 or cells[0] in ("Kind", "") or set(cells[0]) <= {"-", " "}:
            continue
        kind, term, years, issuer, support = cells[:5]
        rows[planted_gap_key(kind, term, int(years) if years else None, issuer or None)] = Support(
            support
        )
    return rows


def _occurrences(text: str, span: str) -> list[tuple[int, int]]:
    found = []
    start = text.find(span)
    while start != -1:
        found.append((start, start + len(span)))
        start = text.find(span, start + 1)
    return found


def _check_requirement(
    label: LabeledRequirement,
    posting: str,
    bank: Bank,
    planted: dict[str, Support],
) -> list[str]:
    problems: list[str] = []
    name = label.id
    if label.span not in posting:
        problems.append(f"{name}: span is not an exact substring of the posting")
    facts = {fact.id: fact for fact in bank.facts}
    for fact_id in label.fact_ids:
        fact = facts.get(fact_id)
        if fact is None:
            problems.append(f"{name}: fact {fact_id} is not in the sample bank")
        elif not fact.is_verified:
            problems.append(f"{name}: fact {fact_id} is not verified")
        elif fact.share is not Share.SHAREABLE:
            problems.append(f"{name}: fact {fact_id} is local only and is never shown to a model")
    strong = label.expected_support is Support.STRONG
    if (label.expected_status is Status.SUPPORTED) != strong:
        problems.append(f"{name}: expected_status must be gap unless expected_support is strong")
    if label.expected_support is Support.NONE and label.fact_ids:
        problems.append(f"{name}: support none must not cite any fact")
    if label.expected_support is not Support.NONE and not label.fact_ids:
        problems.append(f"{name}: strong or partial support must cite at least one fact")
    if label.planted_gap is not None:
        problems.extend(_check_planted(label, planted))
    return problems


def _check_planted(label: LabeledRequirement, planted: dict[str, Support]) -> list[str]:
    name, key = label.id, label.planted_gap
    if key not in planted:
        return [f"{name}: planted gap {key} is not in PLANTED_GAPS.md"]
    own = planted_gap_key(label.kind.value, label.term, label.years, label.issuer)
    if own != key:
        return [
            f"{name}: planted gap {key} does not match kind, term, years and issuer "
            "of the requirement"
        ]
    if planted[key] is not label.expected_support:
        return [
            f"{name}: planted gap {key} expects support {planted[key].value}, "
            f"not {label.expected_support.value}"
        ]
    return []


def _check_cues(labels: Labels, posting: str) -> list[str]:
    """Problems with the cue sentences. An unlabeled posting sentence is quoted on purpose: the
    postings are our own committed fixtures, so the text is known and helps find the gap."""
    problems: list[str] = []
    labeled: list[tuple[int, int]] = []
    for number, cue in enumerate(labels.cue_sentences, start=1):
        spans = _occurrences(posting, cue.span)
        if not spans:
            problems.append(f"cue sentence {number}: span is not an exact substring of the posting")
        labeled.extend(spans)
    for start, end in split_sentences(posting):
        sentence = posting[start:end]
        if not has_cue(sentence) or is_importance_heading(sentence):
            continue
        if not any(s < end and e > start for s, e in labeled):
            problems.append(f"posting sentence with a cue word is not labeled: {sentence}")
    return problems


def validate_labels(labels: Labels, posting: str, bank: Bank, planted: dict[str, Support]) -> None:
    """Raise LabelError listing every problem. Returns nothing when the labels are sound."""
    problems: list[str] = []
    seen: set[str] = set()
    for label in labels.requirements:
        if label.id in seen:
            problems.append(f"{label.id}: id is used more than once")
        seen.add(label.id)
        problems.extend(_check_requirement(label, posting, bank, planted))
    problems.extend(_check_cues(labels, posting))
    if problems:
        raise LabelError(problems)


def _git(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=directory, capture_output=True, text=True, check=False
    )


def _holds(directory: Path, *args: str) -> bool:
    return _git(directory, *args).returncode == 0


def _merge_in_progress(directory: Path) -> bool:
    return _holds(directory, "rev-parse", "-q", "--verify", "MERGE_HEAD")


def _is_merge_result(directory: Path) -> bool:
    """While a merge is under way, the merged file is the one in the index when nobody edited it.

    The index copy must equal the file on either side of the merge and the working copy must
    equal the index, so an edit made during the merge is still refused."""
    if not _merge_in_progress(directory):
        return False
    if not _holds(directory, "diff", "--quiet", "--", "labels.yaml"):
        return False
    return any(
        _holds(directory, "diff", "--cached", "--quiet", side, "--", "labels.yaml")
        for side in ("HEAD", "MERGE_HEAD")
        if _holds(directory, "cat-file", "-e", f"{side}:./labels.yaml")
    )


def require_committed_labels(fixture_dir: Path) -> None:
    """Refuse a case whose labels.yaml is not tracked and identical to the committed file.

    During a merge in progress the file the merge brought in counts as committed."""
    tracked = _git(fixture_dir, "ls-files", "--error-unmatch", "labels.yaml")
    if tracked.returncode != 0:
        raise LabelsNotCommitted(f"{fixture_dir.name}: labels.yaml is not tracked by git")
    if _is_merge_result(fixture_dir):
        return
    head = _git(fixture_dir, "cat-file", "-e", "HEAD:./labels.yaml")
    if head.returncode != 0:
        raise LabelsNotCommitted(f"{fixture_dir.name}: labels.yaml is not committed yet")
    changed = _git(fixture_dir, "diff", "--quiet", "HEAD", "--", "labels.yaml")
    if changed.returncode != 0:
        raise LabelsNotCommitted(f"{fixture_dir.name}: labels.yaml differs from the commit")
