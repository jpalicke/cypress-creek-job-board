-- ABOUTME: Creates the discovery report table: one stored gap report per run id.
-- ABOUTME: The run id covers the text, bank, backend and model, so it is the cache key.
CREATE TABLE discovery_report (
    run_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('complete', 'incomplete')),
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
