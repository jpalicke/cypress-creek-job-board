-- ABOUTME: Creates the schema_version table the migration runner uses to record applied migrations.
-- ABOUTME: Every later migration adds its own tables; this one holds no domain data.
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
