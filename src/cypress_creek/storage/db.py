# ABOUTME: SQLite connection helper and a migration runner over numbered .sql files.
# ABOUTME: Each migration runs in one transaction and is recorded in the schema_version table.
import os
import re
import sqlite3
from pathlib import Path

DATA_DIR_ENV = "CYPRESS_CREEK_DATA_DIR"
DEFAULT_DATA_DIR = Path("data")
DATABASE_FILENAME = "cypress_creek.sqlite3"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

MIGRATION_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(Exception):
    """Raised when the migration folder or a migration is unusable. Never swallowed."""


def data_dir() -> Path:
    configured = os.environ.get(DATA_DIR_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_DATA_DIR


def database_path() -> Path:
    return data_dir() / DATABASE_FILENAME


def connect(path: Path) -> sqlite3.Connection:
    """Open the database, creating the file and parent folders. Transactions are explicit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    """The highest applied migration, or 0 for a database no migration has touched."""
    return max(_applied(conn), default=0)


def migrate(conn: sqlite3.Connection, folder: Path = MIGRATIONS_DIR) -> list[int]:
    """Apply every migration the database has not seen, in order. Returns the versions applied."""
    migrations = _read_migrations(folder)
    applied = _applied(conn)
    for version, name in applied.items():
        if version not in migrations:
            raise MigrationError(
                f"database is at version {max(applied)}, newer than the code "
                f"(highest known {max(migrations)})"
            )
        if migrations[version][0] != name:
            raise MigrationError(
                f"migration {version:04d} was applied as {name!r} "
                f"but the folder has {migrations[version][0]!r}"
            )
    pending = [version for version in sorted(migrations) if version not in applied]
    for version in pending:
        name, sql = migrations[version]
        _apply(conn, version, name, sql)
    return pending


def _applied(conn: sqlite3.Connection) -> dict[int, str]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if not exists:
        return {}
    rows = conn.execute("SELECT version, name FROM schema_version").fetchall()
    return {version: name for version, name in rows}


def _read_migrations(folder: Path) -> dict[int, tuple[str, str]]:
    """Read and check the whole folder up front, so a bad folder runs nothing."""
    if not folder.is_dir():
        raise MigrationError(f"migrations folder not found: {folder}")
    found: dict[int, tuple[str, str]] = {}
    for path in sorted(folder.glob("*.sql")):
        match = MIGRATION_NAME.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: expected a name like 0001_short_name.sql")
        version = int(match.group(1))
        if version in found:
            raise MigrationError(f"{path.name}: duplicate version {version}")
        if version != len(found) + 1:
            raise MigrationError(f"{path.name}: gap before version {version}")
        try:
            sql = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise MigrationError(f"{path.name}: not valid utf-8 ({error.reason})") from error
        found[version] = (match.group(2), sql)
    if not found:
        raise MigrationError(f"no migrations found in {folder}")
    return found


def _apply(conn: sqlite3.Connection, version: int, name: str, sql: str) -> None:
    """Run one migration and its version record as a single transaction."""
    record = (
        f"INSERT INTO schema_version (version, name, applied_at) "
        f"VALUES ({version}, '{name}', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));"
    )
    try:
        conn.executescript(f"BEGIN;\n{sql}\n;\n{record}\nCOMMIT;")
    except sqlite3.Error as error:
        if conn.in_transaction:
            conn.rollback()
        raise MigrationError(
            f"{version:04d}_{name}.sql failed and was rolled back: {error}"
        ) from error
