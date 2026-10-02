# ADR 0005: SQLite for mutable state, numbered SQL migrations, data directory

Status: proposed (card B6b)

## Decision
- The fact bank and config stay YAML. Mutable application state is one SQLite file, using the standard library `sqlite3` module and no ORM.
- Schema changes are numbered `.sql` files in `src/cypress_creek/storage/migrations/` (`NNNN_short_name.sql`, starting at 1, no gaps). They apply in order and each is recorded in a `schema_version` table.
- Each migration and its version row run in one explicit transaction. A failure rolls back that file and raises `MigrationError` naming it. The folder is validated in full before anything runs.
- A database that is newer than the code, or whose applied name differs from the file of that number, is refused.
- The database lives in `CYPRESS_CREEK_DATA_DIR` (default `data/`, gitignored) as `cypress_creek.sqlite3`.
- There are no checksums and no downgrades. Migrations are never edited once applied.

## Why
SQLite needs no server, ships with Python and makes a clone and run story simple. Plain SQL files are reviewable and need no migration library. Rolling back per file means a half applied schema cannot exist, and refusing a newer database stops old code from corrupting data it does not understand. Checksums were left out to keep the runner small; the rename check and review catch the common mistakes, and a later card can add them if it matters.
