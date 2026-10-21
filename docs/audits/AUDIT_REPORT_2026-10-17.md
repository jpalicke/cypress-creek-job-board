# E2b2 documentation audit

Generated: 2026-10-17 | Source commit: `6e7114c` | Scope: E2b2 claims in `README.md`,
`docs/README.md`, `docs/codebase.md` and `docs/evals.md`. Claims were checked against the
working-tree runner and store, not against the older commit alone.

| Result before correction | Count |
| --- | ---: |
| Claims checked | 26 |
| Accurate | 19 |
| Stale | 6 |
| Misleading without resume context | 1 |

## Corrected claims

| Original location | Claim or gap | Evidence and correction |
| --- | --- | --- |
| `README.md:7,11` | The eval runner and trace-saving CLI were future work. | `evals/harness/run.py` runs `analyze` and appends case and terminal records through `EvalStore`. The status and runnable table now describe the CLI. |
| `docs/evals.md:4-5,41,51-52` | The case manifest and CLI were future work. | `evals/cases/technical-smoke.json` and `evals/harness/run.py` exist. The guide now includes dry-run and live commands. |
| `docs/evals.md:22` | The terminal row description omitted failed-case attempts. | `RunTerminal.calls` and `RunState.failed_calls` preserve them in `src/cypress_creek/eval_records.py`. The row description now includes them. |
| `docs/codebase.md:94,180` | The runner and its persisted trace were future work. | `run_live` in `evals/harness/run.py` writes through `EvalStore`; the layout, diagram and trace description now show it. |
| `docs/codebase.md:173` | Unknown usage blocks later calls, without saying what happens after restart. | `_resume_budget` reserves a context-sized input ceiling and stage output cap for unknown usage. The guide now distinguishes same-invocation blocking from resume accounting. |
| `docs/README.md:10,51-52` | The index and configuration list omitted the live CLI and separate output paths. | The index now links the runner guide and explains SQLite `--out` versus scratch JSONL `--export`. |

The repeated pattern was future-tense language left after the runner landed. Searches across
these four documents for `eval`, `runner`, `JSONL`, `scratch` and `dry-run` found the additional
layout, configuration and run-command gaps above. The code inventory confirmed the case
manifest, CLI, SQLite store, trace records and scratch ignore rule are all present. No E2b2
claim in this scope remains in the human review queue.

## Command verification

- The documented dry run produced one exact initial extraction call, an entailment initial-call
  upper bound of 40 and a provider-attempt upper bound of 205, without a provider request.
- The live Ollama command completed one case in SQLite and wrote a scratch JSONL snapshot.
  `load_run` read it as `complete` with one case, one observed call and no pending pair. A
  repeat invocation with the same run identity returned complete without another case.
- The record contract tests passed: 18 tests. The sample bank checks passed: 28 tests.
  The sample bank command printed `25 facts, 25 verified; unverified: []`.

The scratch export is audit data. E3 hand labels are still required before publication under
`evals/results/` or any benchmark claim.
