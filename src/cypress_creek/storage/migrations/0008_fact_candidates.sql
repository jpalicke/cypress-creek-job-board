-- ABOUTME: Creates the table of facts proposed from a resume, kept apart from the fact bank.
-- ABOUTME: A candidate is pending until a person approves or rejects it, and it is never a fact.
CREATE TABLE fact_candidate (
    id TEXT PRIMARY KEY,
    resume_hash TEXT NOT NULL,
    claim TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    source TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'rejected')),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    fact_id TEXT
);
CREATE INDEX fact_candidate_state ON fact_candidate (state);
