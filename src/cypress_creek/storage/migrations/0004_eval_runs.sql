-- ABOUTME: Stores eval run headers and ordered case or terminal records as JSON.
-- ABOUTME: Unique case pairs and foreign keys protect resumable run history.
CREATE TABLE eval_run (
    run_id TEXT PRIMARY KEY,
    header_json TEXT NOT NULL CHECK (json_valid(header_json))
);

CREATE TABLE eval_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES eval_run(run_id),
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    CHECK (json_extract(record_json, '$.record_type') IN ('case', 'terminal')),
    CHECK (json_extract(record_json, '$.run_id') IS run_id)
);

CREATE INDEX eval_event_run_order ON eval_event (run_id, id);
CREATE UNIQUE INDEX eval_case_once ON eval_event (
    run_id,
    json_extract(record_json, '$.case_id'),
    json_extract(record_json, '$.repeat')
) WHERE json_extract(record_json, '$.record_type') = 'case';
