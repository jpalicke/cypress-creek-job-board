# ABOUTME: Tests loading the fact bank from real YAML files in a temp directory.
# ABOUTME: Covers valid and invalid banks, hostile YAML, path configuration and file level errors.
from datetime import date
from pathlib import Path

import pytest

from cypress_creek.facts import BankLoadError, FactValidationError, load_bank
from cypress_creek.facts.loader import BANK_PATH_ENV, DEFAULT_BANK_PATH, bank_path

VALID = """
facts:
  - id: F-0001
    claim: Built a nightly report generator for a fictional logistics team.
    kind: project
    employer: Example Freight Co
    start: 2022-01-01
    end: 2023-01-01
    tags:
      - {name: python, level: expert}
    verified_on: 2024-05-01
    evidence: {type: repo, pointer: "https://example.invalid/repo"}
    share: shareable
  - id: F-0002
    claim: Studied algorithms at a fictional university.
    kind: education
    evidence: {type: certificate, pointer: transcript.pdf}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "bank.yaml"
    path.write_text(text, encoding="utf8")
    return path


def test_valid_bank_file_loads_and_splits_verified_from_unverified(tmp_path: Path) -> None:
    bank = load_bank(write(tmp_path, VALID))
    assert [fact.id for fact in bank.verified_facts()] == ["F-0001"]
    assert bank.unverified_ids() == ["F-0002"]
    assert bank.facts[0].verified_on == date(2024, 5, 1)


def test_strict_load_rejects_the_unverified_fact(tmp_path: Path) -> None:
    with pytest.raises(FactValidationError) as caught:
        load_bank(write(tmp_path, VALID), strict=True)
    assert (caught.value.fact_id, caught.value.field) == ("F-0002", "verified_on")


def test_invalid_field_names_the_fact_and_field(tmp_path: Path) -> None:
    text = VALID.replace("kind: project", "kind: hobby")
    with pytest.raises(FactValidationError) as caught:
        load_bank(write(tmp_path, text))
    assert (caught.value.fact_id, caught.value.field) == ("F-0001", "kind")


def test_aliases_are_refused(tmp_path: Path) -> None:
    text = "facts:\n  - &a {id: F-0001}\n  - *a\n"
    with pytest.raises(BankLoadError, match="alias"):
        load_bank(write(tmp_path, text))


def test_billion_laughs_is_refused(tmp_path: Path) -> None:
    text = (
        "a: &a [x, x, x, x, x, x, x, x, x]\n"
        "b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]\n"
        "c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b]\n"
        "facts: []\n"
    )
    with pytest.raises(BankLoadError, match="alias"):
        load_bank(write(tmp_path, text))


def test_python_object_tags_are_refused(tmp_path: Path) -> None:
    text = "facts: !!python/object/apply:os.getcwd []\n"
    with pytest.raises(BankLoadError):
        load_bank(write(tmp_path, text))


def test_oversized_file_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, "facts: []\n" + "# padding\n" * 200_000)
    with pytest.raises(BankLoadError, match="too large"):
        load_bank(path)


@pytest.mark.parametrize("text", ["", "- just\n- a list\n", "facts: not-a-list\n", "facts: [1]\n"])
def test_wrong_shape_is_a_bank_load_error(tmp_path: Path, text: str) -> None:
    with pytest.raises(BankLoadError):
        load_bank(write(tmp_path, text))


def test_missing_file_is_a_bank_load_error(tmp_path: Path) -> None:
    with pytest.raises(BankLoadError, match="not found"):
        load_bank(tmp_path / "nope.yaml")


def test_broken_yaml_is_a_bank_load_error(tmp_path: Path) -> None:
    with pytest.raises(BankLoadError, match="YAML"):
        load_bank(write(tmp_path, "facts: [unclosed\n"))


def test_default_path_is_the_gitignored_private_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BANK_PATH_ENV, raising=False)
    assert bank_path() == DEFAULT_BANK_PATH
    assert DEFAULT_BANK_PATH.parts[0] == "facts.private"


def test_path_is_configurable_through_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BANK_PATH_ENV, str(tmp_path / "mine.yaml"))
    assert bank_path() == tmp_path / "mine.yaml"
    path = write(tmp_path, VALID)
    path.rename(tmp_path / "mine.yaml")
    assert len(load_bank().facts) == 2
