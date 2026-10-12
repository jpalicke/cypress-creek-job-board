# ADR 0018: Eval resume identity includes every audited input

Status: accepted (Joe P, card E2a)

## Decision
- An eval JSONL file has one header with the git commit, provider, exact model, prompt hashes, schema versions, fixture set hash, bank hash, ordered case IDs and repeat count.
- `RunHeader.run_id` is SHA-256 over canonical JSON of that header, including the record format version. Resume requires the same header and skips only case and repeat pairs already recorded as complete rows.
- A complete terminal record is valid only after every planned pair has a case row. A failed terminal retains its reason and the completed pairs, so the same run can resume.
- The eval run ID is distinct from the pipeline report ID in [ADR 0014](0014-run-id-is-derived-from-the-inputs.md). The report ID groups the same posting, bank, backend and model even across prompt changes; eval resume must separate those changes.

## Why
- Reusing a row after a prompt, schema, fixture or code change would mix different experiments in one run file.
- A terminal record distinguishes a finished run from a process that stopped after writing some valid rows.
- Keeping the report ID's existing meaning avoids changing product provenance to satisfy eval bookkeeping.

## Consequences
- Moving to another commit or changing the case plan starts a different eval run, even if the posting and model are unchanged.
- Scratch run files stay gitignored. Published results require hand labels and a separate review.
