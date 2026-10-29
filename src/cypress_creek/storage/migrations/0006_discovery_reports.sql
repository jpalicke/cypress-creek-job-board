-- ABOUTME: Creates the discovery report table: one stored gap report per run id and pipeline version.
-- ABOUTME: The run id covers text, bank, backend and model, the version covers the code that judged it.
CREATE TABLE discovery_report (
    run_id TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('complete', 'incomplete')),
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, pipeline_version)
);
