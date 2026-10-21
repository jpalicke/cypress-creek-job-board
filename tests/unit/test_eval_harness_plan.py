# ABOUTME: Checks deterministic eval case loading and identity before provider work begins.
# ABOUTME: Duplicate case IDs and malformed fixtures fail before a run can be stored.
import json
from pathlib import Path

import pytest

from cypress_creek.config import parse_settings
from cypress_creek.facts import load_bank
from cypress_creek.facts.hashing import bank_hash
from cypress_creek.facts.models import Bank
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.providers.ollama import OllamaProvider
from evals.harness.run import BANK_PATH, _header, fixture_set_hash, load_cases


def _manifest(path: Path, cases: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")


def test_case_manifest_normalizes_postings_and_keeps_an_explicit_date(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    _manifest(
        path,
        [{"id": "technical-smoke", "posting": "Needs  Ｐｙｔｈｏｎ.  ", "as_of": "2024-06-01"}],
    )

    (case,) = load_cases(path)

    assert case.id == "technical-smoke"
    assert case.posting.text == "Needs Python."
    assert case.posting.created_at.date().isoformat() == "2024-06-01"
    assert case.posting.text_hash == text_hash("Needs Python.")


def test_fixture_identity_changes_with_text_date_and_case_order(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    first = {"id": "first", "posting": "Needs Python.", "as_of": "2024-06-01"}
    second = {"id": "second", "posting": "Needs Go.", "as_of": "2024-06-01"}
    _manifest(path, [first, second])
    original = fixture_set_hash(load_cases(path))
    assert fixture_set_hash(load_cases(path)) == original

    _manifest(path, [second, first])
    assert fixture_set_hash(load_cases(path)) != original
    _manifest(path, [first, {**second, "as_of": "2024-06-02"}])
    assert fixture_set_hash(load_cases(path)) != original
    _manifest(path, [first, {**second, "posting": "Needs Rust."}])
    assert fixture_set_hash(load_cases(path)) != original


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    case = {"id": "same", "posting": "Needs Python.", "as_of": "2024-06-01"}
    _manifest(path, [case, case])

    with pytest.raises(ValueError, match="duplicate case"):
        load_cases(path)


def test_run_header_hashes_the_bank_snapshot_used_for_analysis(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    _manifest(path, [{"id": "one", "posting": "Needs Python.", "as_of": "2024-06-01"}])
    full_bank = load_bank(BANK_PATH, strict=True)
    snapshot = Bank(facts=full_bank.facts[:-1])
    provider = OllamaProvider(parse_settings({"provider": "ollama", "model": "qwen3.5:0.8b"}))

    header = _header(load_cases(path), 1, provider, "ollama", "qwen3.5:0.8b", bank=snapshot)

    assert header.bank_hash == bank_hash(snapshot)
    assert header.bank_hash != bank_hash(full_bank)
