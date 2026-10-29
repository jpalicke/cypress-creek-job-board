-- ABOUTME: Adds the posting and report tables used by the API. Posting text lives in the database.
-- ABOUTME: A report row keeps the whole GapReport as JSON and must point at a stored posting.
CREATE TABLE posting (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('paste', 'link', 'pdf', 'feed')),
    text TEXT NOT NULL CHECK (length(text) > 0),
    text_hash TEXT NOT NULL CHECK (length(text_hash) = 64),
    origin_url TEXT,
    extractor_name TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    warnings_json TEXT NOT NULL CHECK (json_valid(warnings_json)),
    created_at TEXT NOT NULL
);

CREATE TABLE report (
    id TEXT PRIMARY KEY,
    posting_id TEXT NOT NULL REFERENCES posting(id),
    status TEXT NOT NULL CHECK (status IN ('complete', 'incomplete')),
    report_json TEXT NOT NULL CHECK (json_valid(report_json)),
    verdicts_json TEXT NOT NULL CHECK (json_valid(verdicts_json)),
    created_at TEXT NOT NULL
);

CREATE INDEX report_by_posting ON report (posting_id, created_at);
