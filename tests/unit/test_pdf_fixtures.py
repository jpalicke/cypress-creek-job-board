# ABOUTME: Checks the hostile PDF generator: deterministic, complete, and in step with the files.
# ABOUTME: Regenerating into a temp folder must give byte identical files to the committed ones.
import hashlib
import importlib.util
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "fixtures" / "pdf"


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("pdf_generate", FOLDER / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_regenerating_gives_byte_identical_files(tmp_path: Path) -> None:
    written = _generator().write(tmp_path)

    assert written
    for name in written:
        assert _digest(tmp_path / name) == _digest(FOLDER / name), name


def test_generating_twice_gives_the_same_bytes(tmp_path: Path) -> None:
    generator = _generator()

    assert generator.build_all() == generator.build_all()


def test_every_committed_pdf_is_listed_in_cases_and_the_reverse() -> None:
    cases = yaml.safe_load((FOLDER / "cases.yaml").read_text(encoding="utf-8"))["cases"]

    listed = {case["file"] for case in cases}
    assert listed == {path.name for path in FOLDER.glob("*.pdf")}


def test_every_attacked_case_names_a_clean_twin_that_exists() -> None:
    cases = yaml.safe_load((FOLDER / "cases.yaml").read_text(encoding="utf-8"))["cases"]

    for case in cases:
        if "pair" in case:
            assert (FOLDER / case["pair"]).is_file()


def test_the_fixtures_stay_small_enough_to_commit() -> None:
    assert all(path.stat().st_size < 400_000 for path in FOLDER.glob("*.pdf"))
