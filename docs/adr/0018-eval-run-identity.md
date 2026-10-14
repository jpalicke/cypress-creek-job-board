# ADR 0018: Eval resume identity includes every audited input

Status: accepted (Joe P, card E2a)

## Decision
- An eval run has one header with the git commit, provider, exact model, prompt hashes, schema versions, fixture set hash, bank hash, ordered case IDs and repeat count. SQLite is the live store for that header and its ordered JSON case and terminal records. JSONL is an audit export.
- `RunHeader.run_id` is SHA-256 over canonical JSON of that header, including the record format version. Resume requires the same header and skips only case and repeat pairs already recorded as complete rows.
- A complete terminal record is valid only after every planned pair has a case row. A failed terminal retains its reason and the completed pairs, so the same run can resume.
- Each appended record commits in one SQLite transaction. Export validates a database snapshot and creates a JSONL file without overwriting an existing export. JSONL reads do not change live run state.
- The eval run ID is distinct from the pipeline report ID in [ADR 0014](0014-run-id-is-derived-from-the-inputs.md). The report ID groups the same posting, bank, backend and model even across prompt changes; eval resume must separate those changes.

## Why
- Reusing a record after a prompt, schema, fixture or code change would mix different experiments in one run.
- A terminal record distinguishes a finished run from a process that stopped after writing some valid rows.
- SQLite transactions protect completed case pairs from interrupted writes and follow the project's existing mutable-state decision in [ADR 0005](0005-sqlite-and-migrations.md).
- Keeping the report ID's existing meaning avoids changing product provenance to satisfy eval bookkeeping.

## Consequences
- Moving to another commit or changing the case plan starts a different eval run, even if the posting and model are unchanged.
- The SQLite file and scratch exports stay gitignored. Published JSONL exports require hand labels and a separate review.
- Existing JSONL files remain readable for audit but are not automatically imported into SQLite for resume.
