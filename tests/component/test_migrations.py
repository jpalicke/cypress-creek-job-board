# ABOUTME: Tests the SQLite connection helper and migration runner against real temp database files.
# ABOUTME: Covers ordering, idempotence, the version table, rollback and hostile migration folders.
import sqlite3
from pathlib import Path

import pytest

from cypress_creek.storage.db import (
    MIGRATIONS_DIR,
    MigrationError,
    connect,
    migrate,
    schema_version,
)


def write_migration(folder: Path, name: str, sql: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(sql, encoding="utf-8")


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = tmp_path / "migrations"
    write_migration(
        path,
        "0001_schema_version.sql",
        (MIGRATIONS_DIR / "0001_schema_version.sql").read_text("utf-8"),
    )
    write_migration(path, "0002_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY);\n")
    write_migration(path, "0003_more.sql", "CREATE TABLE more (id INTEGER PRIMARY KEY);\n")
    return path


def test_connect_creates_the_file_and_its_parent_folders(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "app.sqlite3"
    conn = connect(path)
    conn.close()
    assert path.is_file()


def test_connect_turns_foreign_keys_on(tmp_path: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    conn.close()


def test_a_fresh_database_has_version_zero(tmp_path: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    assert schema_version(conn) == 0
    conn.close()


def test_migrations_apply_in_order_and_are_recorded(tmp_path: Path, folder: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    assert migrate(conn, folder) == [1, 2, 3]
    assert {"schema_version", "things", "more"} <= tables(conn)
    rows = conn.execute("SELECT version, name FROM schema_version ORDER BY version").fetchall()
    assert rows == [(1, "schema_version"), (2, "things"), (3, "more")]
    assert schema_version(conn) == 3
    conn.close()


def test_a_second_run_applies_nothing_and_does_not_error(tmp_path: Path, folder: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    migrate(conn, folder)
    assert migrate(conn, folder) == []
    assert schema_version(conn) == 3
    conn.close()


def test_a_reopened_database_keeps_its_versions(tmp_path: Path, folder: Path) -> None:
    path = tmp_path / "app.sqlite3"
    conn = connect(path)
    migrate(conn, folder)
    conn.close()
    conn = connect(path)
    assert migrate(conn, folder) == []
    conn.close()


def test_only_new_migrations_apply_on_a_later_run(tmp_path: Path, folder: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    migrate(conn, folder)
    write_migration(folder, "0004_late.sql", "CREATE TABLE late (id INTEGER PRIMARY KEY);\n")
    assert migrate(conn, folder) == [4]
    assert "late" in tables(conn)
    conn.close()


def test_a_failing_migration_rolls_back_and_fails_loudly(tmp_path: Path, folder: Path) -> None:
    write_migration(
        folder,
        "0004_broken.sql",
        "CREATE TABLE half_done (id INTEGER PRIMARY KEY);\nINSERT INTO no_such_table VALUES (1);\n",
    )
    conn = connect(tmp_path / "app.sqlite3")
    with pytest.raises(MigrationError, match="0004_broken.sql"):
        migrate(conn, folder)
    assert "half_done" not in tables(conn)
    assert schema_version(conn) == 3
    assert not conn.in_transaction
    conn.close()


def test_a_migration_that_was_already_recorded_is_not_rerun_after_a_later_failure(
    tmp_path: Path, folder: Path
) -> None:
    write_migration(folder, "0004_broken.sql", "SELECT * FROM no_such_table;\n")
    conn = connect(tmp_path / "app.sqlite3")
    with pytest.raises(MigrationError):
        migrate(conn, folder)
    (folder / "0004_broken.sql").unlink()
    write_migration(folder, "0004_fixed.sql", "CREATE TABLE fixed (id INTEGER PRIMARY KEY);\n")
    assert migrate(conn, folder) == [4]
    conn.close()


def test_the_shipped_migrations_apply_to_a_real_database(tmp_path: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    applied = migrate(conn)
    assert applied[0] == 1
    assert schema_version(conn) == applied[-1]
    conn.close()


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (["0001_schema_version.sql", "0001_again.sql"], "duplicate version 1"),
        (["0001_schema_version.sql", "0003_skip.sql"], "gap before version 3"),
        (["0002_first.sql"], "gap before version 2"),
        (["0001_schema_version.sql", "notes.sql"], "notes.sql"),
        (["0001_schema_version.sql", "02_short.sql"], "02_short.sql"),
        (["0001_schema_version.sql", "0002_Bad Name.sql"], "0002_Bad Name.sql"),
    ],
)
def test_a_bad_migration_folder_is_refused_before_anything_runs(
    tmp_path: Path, names: list[str], message: str
) -> None:
    folder = tmp_path / "migrations"
    shipped = (MIGRATIONS_DIR / "0001_schema_version.sql").read_text("utf-8")
    for name in names:
        write_migration(folder, name, shipped if name.startswith("0001_schema") else "SELECT 1;\n")
    conn = connect(tmp_path / "app.sqlite3")
    with pytest.raises(MigrationError, match=message):
        migrate(conn, folder)
    assert tables(conn) == set()
    conn.close()


def test_a_missing_or_empty_folder_is_refused(tmp_path: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    with pytest.raises(MigrationError, match="not found"):
        migrate(conn, tmp_path / "nope")
    (tmp_path / "empty").mkdir()
    with pytest.raises(MigrationError, match="no migrations"):
        migrate(conn, tmp_path / "empty")
    conn.close()


def test_a_database_newer_than_the_code_is_refused(tmp_path: Path, folder: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    migrate(conn, folder)
    (folder / "0003_more.sql").unlink()
    with pytest.raises(MigrationError, match="newer than the code"):
        migrate(conn, folder)
    conn.close()


def test_a_renamed_applied_migration_is_refused(tmp_path: Path, folder: Path) -> None:
    conn = connect(tmp_path / "app.sqlite3")
    migrate(conn, folder)
    (folder / "0002_things.sql").rename(folder / "0002_renamed.sql")
    with pytest.raises(MigrationError, match="0002"):
        migrate(conn, folder)
    conn.close()


def test_a_migration_file_that_is_not_utf8_is_refused(tmp_path: Path, folder: Path) -> None:
    (folder / "0004_binary.sql").write_bytes(b"\xff\xfe\x00bad")
    conn = connect(tmp_path / "app.sqlite3")
    with pytest.raises(MigrationError, match="0004_binary.sql"):
        migrate(conn, folder)
    assert schema_version(conn) == 0
    conn.close()
