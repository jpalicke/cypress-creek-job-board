# ABOUTME: Tests strict eval run metadata, case records and JSONL round trips.
# ABOUTME: Resume identity must change whenever audited inputs or prompt versions change.
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cypress_creek.eval_records import RunHeader, load_run, write_header


def _header(**changes: object) -> RunHeader:
    fields: dict[str, object] = {
        "git_commit": "a" * 40,
        "backend": "ollama",
        "model": "qwen3.5:0.8b",
        "prompt_hashes": {"extract": "b" * 64, "entail": "c" * 64},
        "schema_versions": {"extract": 1, "entail": 1},
        "fixture_set_hash": "d" * 64,
        "bank_hash": "e" * 64,
        "case_ids": ["case-1"],
        "repeats": 3,
    }
    fields.update(changes)
    return RunHeader.model_validate(fields)


def test_header_round_trips_commit_model_and_prompt_hash(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    header = _header()

    write_header(path, header)

    state = load_run(path)
    assert state.header == header
    assert state.header.git_commit == "a" * 40
    assert state.header.model == "qwen3.5:0.8b"
    assert state.header.prompt_hashes["extract"] == "b" * 64
    assert state.pending_pairs == {("case-1", 1), ("case-1", 2), ("case-1", 3)}


@pytest.mark.parametrize("missing", ["git_commit", "model", "prompt_hashes"])
def test_header_rejects_missing_audit_field(missing: str) -> None:
    fields = _header().model_dump()
    del fields[missing]
    with pytest.raises(ValidationError):
        RunHeader.model_validate(fields)


def test_resume_identity_changes_with_prompt_or_fixture() -> None:
    first = _header()
    assert _header(prompt_hashes={"extract": "f" * 64, "entail": "c" * 64}).run_id != first.run_id
    assert _header(fixture_set_hash="f" * 64).run_id != first.run_id


def test_header_rejects_duplicate_cases_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _header(case_ids=["case-1", "case-1"])
    with pytest.raises(ValidationError):
        RunHeader.model_validate({**_header().model_dump(), "extra": True})


def test_header_rejects_prompt_without_matching_schema_version() -> None:
    with pytest.raises(ValidationError, match="prompt and schema stages"):
        _header(schema_versions={"extract": 1})


@pytest.mark.parametrize("missing", ["record_type", "format_version"])
def test_run_file_rejects_header_without_explicit_format_field(
    tmp_path: Path, missing: str
) -> None:
    path = tmp_path / "run.jsonl"
    write_header(path, _header())
    row = json.loads(path.read_text(encoding="utf-8"))
    del row[missing]
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header format"):
        load_run(path)
