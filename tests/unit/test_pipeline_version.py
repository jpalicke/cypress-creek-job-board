# ABOUTME: Tests the pipeline version: a digest of the code, prompts and config that judge a report.
# ABOUTME: It changes when any of those files change, so cached scores never outlive their judges.
from pathlib import Path

from cypress_creek.pipeline.version import fingerprint, pipeline_version


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    (root / "validators").mkdir(parents=True)
    (root / "validators" / "claims.py").write_text("RULE = 1\n", encoding="utf8")
    (root / "prompts").mkdir()
    (root / "prompts" / "extract_v2.txt").write_text("Extract.\n", encoding="utf8")
    return root


def test_the_same_files_give_the_same_version(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    assert fingerprint(root, ["validators", "prompts"]) == fingerprint(
        root, ["validators", "prompts"]
    )
    assert len(fingerprint(root, ["validators", "prompts"])) == 64


def test_changing_a_validator_changes_the_version(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    before = fingerprint(root, ["validators", "prompts"])
    (root / "validators" / "claims.py").write_text("RULE = 2\n", encoding="utf8")
    assert fingerprint(root, ["validators", "prompts"]) != before


def test_changing_a_prompt_changes_the_version(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    before = fingerprint(root, ["validators", "prompts"])
    (root / "prompts" / "extract_v2.txt").write_text("Extract more.\n", encoding="utf8")
    assert fingerprint(root, ["validators", "prompts"]) != before


def test_adding_or_renaming_a_file_changes_the_version(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    before = fingerprint(root, ["validators"])
    (root / "validators" / "claims.py").rename(root / "validators" / "other.py")
    assert fingerprint(root, ["validators"]) != before


def test_the_order_of_the_directories_does_not_matter(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    assert fingerprint(root, ["validators", "prompts"]) == fingerprint(
        root, ["prompts", "validators"]
    )


def test_a_file_outside_the_named_directories_does_not_matter(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    before = fingerprint(root, ["validators"])
    (root / "prompts" / "extract_v2.txt").write_text("Changed.\n", encoding="utf8")
    assert fingerprint(root, ["validators"]) == before


def test_a_missing_directory_is_an_error(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    try:
        fingerprint(root, ["nowhere"])
    except FileNotFoundError:
        return
    raise AssertionError("a missing directory must not give a version")


def test_the_real_pipeline_version_is_a_stable_digest() -> None:
    version = pipeline_version()
    assert len(version) == 64
    assert int(version, 16) >= 0
    assert pipeline_version() == version
