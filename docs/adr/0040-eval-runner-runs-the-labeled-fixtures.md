# ADR 0040: The eval runner runs the committed labeled fixtures

Status: accepted (pod decision under Joe P's delegation, issue #140; his review pending)

## Context

`evals.harness.run` read only JSON case manifests, so no command produced a run the E4 scorer could join to the hand labels. The scorer refuses labels that are not committed, but the run itself did not.

## Decision

- **`--fixtures` is a second case source, exclusive with `--cases`.** The manifest path is unchanged and its tests still pass.
- **Labels are checked before anything else.** The runner calls `require_committed_labels` for every fixture it will run before building a case or creating a provider, so a run can never be made against labels that are still being edited.
- **Case id is the fixture id, and the posting is the fixture text unchanged.** The scorer joins on the id and checks the posting hash, and the label spans index into that exact text. A fixture whose text is not already normalized is refused instead of being quietly rewritten.
- **One definition of the fixture set hash.** The header records `fixtures.fixture_set_hash`, not the manifest hash, so the scorer side and the runner side name the same set. A subset chosen with `--only` hashes only its fixtures and so is a different run identity.
- **A refusal is a typed one line message on stderr and exit code 1**, with no traceback.

## Consequences

- The first published run (E8) is one command per backend, and its export scores with `score.py`.
- The two hash functions still exist (manifest and fixtures) because manifests are still supported; only the fixture one is used for labeled runs.
