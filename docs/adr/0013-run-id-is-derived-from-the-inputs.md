# ADR 0013: The run id is derived from the run's inputs

Status: accepted (Joe P, card D5b)

## Decision
- `run_id` is `run-` followed by the first 16 hex characters of a sha256 over the posting text hash, the fact bank hash, the backend and the model.
- The bank hash is a sha256 over the facts in canonical JSON, sorted by fact id, so reordering the bank file does not change it. It lives in `facts/hashing.py`, the one definition.
- The prompt hashes stay in `Provenance.prompt_hashes` as their own field and are not part of the id.

## Why
- A random id says nothing. A derived one lets two reports be recognised as the same posting, bank and model, and shows at a glance that a changed fact or model gives a new run.
- Prompt hashes are left out so a prompt change shows up in the report without hiding that the inputs were the same.

## Limits
- The model is nondeterministic, so the same id can still come with different supports. The id names the inputs, not the outcome.
- Two runs with the same id are not guaranteed identical. The report's own fields are the record of what happened.
