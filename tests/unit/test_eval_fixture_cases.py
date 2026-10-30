# ABOUTME: Checks that the eval runner loads the committed labeled fixtures as its cases.
# ABOUTME: Fixture ids are the case ids, the set hash is the fixture one, unfrozen labels refuse.
import shutil
import subprocess
from pathlib import Path

import pytest

from evals.harness.fixtures import discover_fixtures, load_fixture
from evals.harness.fixtures import fixture_set_hash as labeled_set_hash
from evals.harness.labels import LabelsNotCommitted
from evals.harness.run import fixture_case_set

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "evals" / "fixtures"
DIRECTORIES = discover_fixtures(FIXTURES)


def test_every_committed_fixture_becomes_a_case_with_its_fixture_id() -> None:
    case_set = fixture_case_set(FIXTURES)

    assert [case.id for case in case_set.cases] == [path.name for path in DIRECTORIES]
    assert len(case_set.cases) >= 6


def test_a_case_posting_is_the_fixture_text_unchanged() -> None:
    case_set = fixture_case_set(FIXTURES)

    for case, directory in zip(case_set.cases, DIRECTORIES, strict=True):
        fixture = load_fixture(directory)
        assert case.posting.text == fixture.text
        assert case.posting.text_hash == fixture.text_hash
        assert case.posting.created_at.date() == fixture.meta.retrieved


def test_the_set_hash_is_the_fixture_set_hash_not_a_second_definition() -> None:
    case_set = fixture_case_set(FIXTURES)

    assert case_set.set_hash == labeled_set_hash([load_fixture(path) for path in DIRECTORIES])


def test_a_chosen_subset_keeps_the_order_and_changes_the_set_hash() -> None:
    chosen = [DIRECTORIES[2].name, DIRECTORIES[0].name]

    subset = fixture_case_set(FIXTURES, only=chosen)

    assert [case.id for case in subset.cases] == [DIRECTORIES[0].name, DIRECTORIES[2].name]
    assert subset.set_hash != fixture_case_set(FIXTURES).set_hash


def test_an_unknown_fixture_id_is_refused() -> None:
    with pytest.raises(ValueError, match="no fixture named nope"):
        fixture_case_set(FIXTURES, only=["nope"])


def _repository(tmp_path: Path) -> Path:
    """A throwaway git repository holding one copied fixture, committed."""
    root = tmp_path / "fixtures"
    root.mkdir()
    shutil.copytree(DIRECTORIES[0], root / DIRECTORIES[0].name)
    for command in (
        ["init", "-q"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "t"],
        ["config", "commit.gpgsign", "false"],
        ["add", "."],
        ["commit", "-q", "-m", "fixtures"],
    ):
        subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
    return root


def test_committed_labels_load(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    assert [case.id for case in fixture_case_set(root).cases] == [DIRECTORIES[0].name]


def test_labels_changed_since_the_commit_refuse_before_any_case_is_built(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    labels = root / DIRECTORIES[0].name / "labels.yaml"
    labels.write_text(labels.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")

    with pytest.raises(LabelsNotCommitted, match="differs from the commit"):
        fixture_case_set(root)


def test_labels_that_were_never_committed_refuse(tmp_path: Path) -> None:
    root = tmp_path / "loose"
    shutil.copytree(DIRECTORIES[0], root / DIRECTORIES[0].name)

    with pytest.raises(LabelsNotCommitted):
        fixture_case_set(root)
