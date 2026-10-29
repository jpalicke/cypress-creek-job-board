# ABOUTME: Checks the committed injection corpus: pairs, payload placement, classes and safety.
# ABOUTME: The payloads are hostile text stored as data only, so the scan keeps them harmless.
import re
import shutil
from pathlib import Path

import pytest
import yaml

from cypress_creek.ingest.normalize import normalize
from evals.harness.injection import (
    INJECTION_FILES,
    AttackClass,
    InjectionFixture,
    discover_injection,
    load_corpus,
    load_injection,
)
from evals.harness.labels import LabelError

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "evals" / "fixtures" / "injection"
DIRECTORIES = discover_injection(CORPUS)
IDS = [directory.name for directory in DIRECTORIES]
FIXTURES = load_corpus(CORPUS)


def test_every_attack_class_except_the_hidden_carrier_has_a_case() -> None:
    covered = {fixture.case.attack_class for fixture in FIXTURES.values()}
    assert covered == set(AttackClass) - {AttackClass.HIDDEN_CARRIER}


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_an_attacked_fixture_pairs_with_its_clean_twin(directory: Path) -> None:
    assert {path.name for path in directory.iterdir()} == set(INJECTION_FILES)
    fixture = load_injection(directory)
    case = fixture.case

    assert case.case_id == directory.name
    start, end = case.offset, case.offset + len(case.payload)
    assert fixture.attacked[start:end] == case.payload
    assert fixture.attacked[:start] + fixture.attacked[end:] == fixture.clean
    assert fixture.attacked != fixture.clean


@pytest.mark.parametrize("fixture", FIXTURES.values(), ids=IDS)
def test_the_normalized_postings_are_usable_and_still_differ(fixture: InjectionFixture) -> None:
    assert fixture.attacked_text != fixture.clean_text
    assert fixture.attacked_hash != fixture.clean_hash
    assert normalize(fixture.clean)[0] == fixture.clean_text
    assert fixture.clean_text.startswith("Data Engineer")


@pytest.mark.parametrize("fixture", FIXTURES.values(), ids=IDS)
def test_a_payload_is_safe_to_store_in_a_public_repo(fixture: InjectionFixture) -> None:
    text = fixture.attacked + (fixture.directory / "payload.yaml").read_text(encoding="utf-8")
    assert not re.search(r"https?://(?!example\.invalid)", text)
    assert not re.search(r"\b(sk-|AKIA|ghp_|xox[bp]-)[A-Za-z0-9]{8,}", text)
    assert "@" not in text
    assert "BEGIN PRIVATE KEY" not in text  # pragma: allowlist secret


def _copy(tmp_path: Path, name: str) -> Path:
    destination = tmp_path / name
    shutil.copytree(CORPUS / name, destination)
    return destination


def test_a_twin_that_differs_by_more_than_the_payload_is_refused(tmp_path: Path) -> None:
    directory = _copy(tmp_path, IDS[0])
    (directory / "clean.txt").write_text(
        (directory / "clean.txt").read_text(encoding="utf-8") + "extra\n", encoding="utf-8"
    )
    with pytest.raises(LabelError, match="more than the payload"):
        load_injection(directory)


def test_a_payload_that_is_not_at_its_offset_is_refused(tmp_path: Path) -> None:
    directory = _copy(tmp_path, IDS[0])
    data = yaml.safe_load((directory / "payload.yaml").read_text(encoding="utf-8"))
    data["offset"] += 1
    (directory / "payload.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(LabelError, match="not in the attacked posting"):
        load_injection(directory)


def test_a_folder_name_that_differs_from_the_case_id_is_refused(tmp_path: Path) -> None:
    directory = _copy(tmp_path, IDS[0])
    renamed = directory.rename(tmp_path / "other-name")
    with pytest.raises(LabelError, match="folder name"):
        load_injection(renamed)


def test_a_missing_file_and_an_unknown_attack_class_are_refused(tmp_path: Path) -> None:
    directory = _copy(tmp_path, IDS[0])
    data = yaml.safe_load((directory / "payload.yaml").read_text(encoding="utf-8"))
    data["attack_class"] = "made_up"
    (directory / "payload.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(LabelError, match="not a valid case"):
        load_injection(directory)
    (directory / "clean.txt").unlink()
    with pytest.raises(LabelError, match="missing clean.txt"):
        load_injection(directory)
