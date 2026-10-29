# ABOUTME: Defines typed eval records shared by SQLite storage and JSONL exports.
# ABOUTME: Run identity includes every input whose change must invalidate resume.
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cypress_creek.pipeline.report import GapReport
from cypress_creek.pipeline.trace import CallRecord as CallRecord
from cypress_creek.pipeline.trace import Digest, Name
from cypress_creek.pipeline.trace import ValidatorRecord as ValidatorRecord

Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class RunHeader(BaseModel):
    """The exact inputs and versions shared by every case in one run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["header"] = "header"
    format_version: Literal[1] = 1
    git_commit: Commit
    backend: Name
    model: Name
    prompt_hashes: dict[str, Digest] = Field(min_length=1)
    schema_versions: dict[str, int] = Field(min_length=1)
    fixture_set_hash: Digest
    bank_hash: Digest
    case_ids: list[Name] = Field(min_length=1)
    repeats: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_cases(self) -> "RunHeader":
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case ids must be unique")
        if self.prompt_hashes.keys() != self.schema_versions.keys():
            raise ValueError("prompt and schema stages must match")
        if any(version <= 0 for version in self.schema_versions.values()):
            raise ValueError("schema versions must be positive")
        return self

    @property
    def run_id(self) -> str:
        """Hash a canonical form of the complete header, including the format version."""
        payload = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CaseRecord(BaseModel):
    """The complete observed result of one case and repeat."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["case"] = "case"
    run_id: Digest
    case_id: Name
    repeat: int = Field(gt=0)
    posting_hash: Digest
    report: GapReport
    calls: list[CallRecord]
    validators: list[ValidatorRecord]


class RunTerminal(BaseModel):
    """An explicit end marker; a failed run can be resumed later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["terminal"] = "terminal"
    run_id: Digest
    status: Literal["complete", "failed"]
    reason: str | None = None
    calls: list[CallRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reason(self) -> "RunTerminal":
        if self.status == "failed" and not self.reason:
            raise ValueError("failed run needs a reason")
        if self.status == "complete" and self.reason is not None:
            raise ValueError("complete run cannot carry a failure reason")
        if self.status == "complete" and self.calls:
            raise ValueError("complete run cannot carry failed attempts")
        return self


@dataclass(frozen=True)
class RunState:
    header: RunHeader
    cases: tuple[CaseRecord, ...] = ()
    terminal: RunTerminal | None = None
    failed_calls: tuple[CallRecord, ...] = ()

    @property
    def pending_pairs(self) -> set[tuple[str, int]]:
        expected = {
            (case_id, repeat)
            for case_id in self.header.case_ids
            for repeat in range(1, self.header.repeats + 1)
        }
        return expected - {(case.case_id, case.repeat) for case in self.cases}

    @property
    def status(self) -> Literal["incomplete", "complete", "failed"]:
        return self.terminal.status if self.terminal else "incomplete"


def _check_case(header: RunHeader, case: CaseRecord, seen: set[tuple[str, int]]) -> None:
    if case.run_id != header.run_id:
        raise ValueError("case run identity does not match header")
    if case.case_id not in header.case_ids or case.repeat > header.repeats:
        raise ValueError("case pair is outside the header plan")
    if (case.case_id, case.repeat) in seen:
        raise ValueError("duplicate case pair")
    if (
        case.report.provenance.backend != header.backend
        or case.report.provenance.model != header.model
    ):
        raise ValueError("report provider identity does not match header")
    _check_calls(header, case.calls)


def _check_calls(header: RunHeader, calls: list[CallRecord]) -> None:
    for call in calls:
        if (
            header.prompt_hashes.get(call.stage) != call.prompt_hash
            or header.schema_versions.get(call.stage) != call.schema_version
        ):
            raise ValueError("call prompt or schema identity does not match header")


def parse_run_rows(rows: Iterable[str], expected_header: RunHeader | None = None) -> RunState:
    """Validate ordered run rows from a database snapshot or a JSONL export."""
    source = iter(rows)
    first = next(source, "")
    if not first:
        raise ValueError("run file has no header")
    header_row = json.loads(first)
    required_fields = {"record_type", "format_version"}
    if not isinstance(header_row, dict) or not required_fields <= header_row.keys():
        raise ValueError("header format fields are required")
    header = RunHeader.model_validate(header_row)
    if expected_header is not None and header != expected_header:
        raise ValueError("run identity does not match expected header")
    cases: list[CaseRecord] = []
    failed_calls: list[CallRecord] = []
    seen: set[tuple[str, int]] = set()
    terminal: RunTerminal | None = None
    for line in source:
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("run row must be an object")
        if terminal is not None and terminal.status == "complete":
            raise ValueError("complete run cannot have later records")
        if row.get("record_type") == "case":
            case = CaseRecord.model_validate(row)
            _check_case(header, case, seen)
            seen.add((case.case_id, case.repeat))
            cases.append(case)
            terminal = None
        elif row.get("record_type") == "terminal":
            terminal = RunTerminal.model_validate(row)
            if terminal.run_id != header.run_id:
                raise ValueError("terminal run identity does not match header")
            _check_calls(header, terminal.calls)
            failed_calls.extend(terminal.calls)
            if terminal.status == "complete" and len(seen) != len(header.case_ids) * header.repeats:
                raise ValueError("complete run has missing case pairs")
        else:
            raise ValueError("unknown run record type")
    return RunState(
        header=header, cases=tuple(cases), terminal=terminal, failed_calls=tuple(failed_calls)
    )


def load_run(path: Path, expected_header: RunHeader | None = None) -> RunState:
    """Read and validate a JSONL export without changing live run state."""
    with path.open(encoding="utf-8") as source:
        return parse_run_rows(source, expected_header=expected_header)
