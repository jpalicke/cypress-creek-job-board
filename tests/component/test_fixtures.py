# ABOUTME: Checks every committed posting fixture: three files, a hash, valid labels and NOTICE.
# ABOUTME: Runs on the real fixture directories, so a stale hash or an unlisted source fails here.
import shutil
from pathlib import Path

import pytest

from cypress_creek.facts import load_bank
from cypress_creek.ingest.normalize import normalize
from evals.harness.fixtures import (
    FIXTURE_FILES,
    Fixture,
    discover_fixtures,
    fixture_set_hash,
    load_fixture,
)
from evals.harness.labels import LabelError, planted_gap_support, validate_labels

ROOT = Path(__file__).parent.parent.parent
FIXTURES = ROOT / "evals" / "fixtures"
BANK = load_bank(ROOT / "evals" / "bank" / "sample_bank.yaml", strict=True)
PLANTED = planted_gap_support(ROOT / "evals" / "bank" / "PLANTED_GAPS.md")
NOTICE = (ROOT / "NOTICE").read_text(encoding="utf-8")

DIRECTORIES = discover_fixtures(FIXTURES)
IDS = [directory.name for directory in DIRECTORIES]


def test_the_first_six_postings_are_fixtures() -> None:
    assert len(DIRECTORIES) == 6
    assert sum(name.startswith("greenhouse-") for name in IDS) == 4
    assert sum(name.startswith("lever-") for name in IDS) == 2


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_a_fixture_directory_has_all_three_files(directory: Path) -> None:
    assert {path.name for path in directory.iterdir()} == set(FIXTURE_FILES)


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_the_meta_hash_matches_the_posting_text(directory: Path) -> None:
    fixture = load_fixture(directory)

    assert fixture.meta.fixture_id == directory.name
    assert fixture.labels.fixture_id == directory.name
    assert fixture.meta.normalized_sha256 == fixture.text_hash


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_the_posting_text_is_already_normalized_and_free_of_personal_data(
    directory: Path,
) -> None:
    text = load_fixture(directory).text

    assert normalize(text)[0] == text
    assert "@" not in text


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_the_labels_validate_against_the_posting_and_the_bank(directory: Path) -> None:
    fixture = load_fixture(directory)

    validate_labels(fixture.labels, fixture.text, BANK, PLANTED)


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_the_labels_say_they_await_review_and_used_no_model_output(directory: Path) -> None:
    provenance = load_fixture(directory).labels.provenance

    assert provenance.model_output_used is False
    assert provenance.review in ("pending", "reviewed")
    assert "Joe P" in provenance.labeled_by


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_notice_lists_the_source_url_and_retrieval_date(directory: Path) -> None:
    meta = load_fixture(directory).meta

    assert meta.url in NOTICE
    assert meta.retrieved.isoformat() in NOTICE


@pytest.mark.parametrize("directory", DIRECTORIES, ids=IDS)
def test_a_replacement_records_what_it_replaces_and_why(directory: Path) -> None:
    meta = load_fixture(directory).meta

    if meta.replaces is not None:
        assert meta.replaces.job_id != meta.job_id
        assert len(meta.replaces.reason) >= 20


def test_the_fixture_set_hash_changes_when_any_posting_changes(tmp_path: Path) -> None:
    fixtures = [load_fixture(directory) for directory in DIRECTORIES]
    before = fixture_set_hash(fixtures)
    assert before == fixture_set_hash(fixtures)

    copy = tmp_path / DIRECTORIES[0].name
    shutil.copytree(DIRECTORIES[0], copy)
    (copy / "posting.txt").write_text(fixtures[0].text + " edited", encoding="utf-8")
    with pytest.raises(LabelError):
        load_fixture(copy)
    changed = Fixture(
        directory=copy,
        text=fixtures[0].text + " edited",
        meta=fixtures[0].meta,
        labels=fixtures[0].labels,
    )

    assert fixture_set_hash([changed, *fixtures[1:]]) != before
