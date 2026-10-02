# ABOUTME: Tests where the database lives: the data directory setting and its default.
# ABOUTME: The CYPRESS_CREEK_DATA_DIR variable wins, otherwise the data folder under the cwd.
from pathlib import Path

import pytest

from cypress_creek.storage.db import DATA_DIR_ENV, DATABASE_FILENAME, data_dir, database_path


def test_the_default_is_a_data_folder_in_the_working_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    assert data_dir() == Path("data")


def test_the_environment_variable_overrides_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert data_dir() == tmp_path


def test_an_empty_variable_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, "  ")
    assert data_dir() == Path("data")


def test_the_database_lives_in_the_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert database_path() == tmp_path / DATABASE_FILENAME
    assert DATABASE_FILENAME.endswith(".sqlite3")
