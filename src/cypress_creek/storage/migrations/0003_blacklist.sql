-- ABOUTME: Creates the blacklist table of blocked company keys, board slugs and domains.
-- ABOUTME: Values are stored already normalized, so one blocked thing has exactly one row.
CREATE TABLE blacklist_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_kind TEXT NOT NULL CHECK (match_kind IN ('company_key', 'slug', 'domain')),
    value TEXT NOT NULL CHECK (value <> ''),
    reason TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (match_kind, value)
);
