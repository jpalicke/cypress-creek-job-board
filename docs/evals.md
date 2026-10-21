# Evals

The eval harness runs dated, fictional postings against the sample fact bank and a real model.
Its CLI saves resumable runs in SQLite and can export JSONL for audit. Hand labels come in E3;
these runs are not benchmark evidence yet.

## Run record format

`cypress_creek.eval_records` defines version 1 of the run record format. Live runs use the
project SQLite database: `eval_run` holds the header JSON and `eval_event` holds ordered case
and terminal JSON. `EvalStore` in `cypress_creek.eval_store` creates a run, appends records in
transactions and reconstructs resume state from the database. A JSONL export starts with a
`header` row, contains one `case` row for each completed case and repeat, and ends with a
`terminal` row when the run succeeds or fails. A run without a terminal is incomplete. A
`failed` terminal carries a reason and can be followed by later case rows and a `complete`
terminal when the same run resumes. A `complete` terminal requires every planned pair.

| Row | Required audit data |
| --- | --- |
| `header` | Git commit, provider, exact model, prompt hashes and schema versions by stage, fixture set hash, bank hash, ordered case IDs and repeat count. `format_version` is 1. |
| `case` | Run ID, case ID, repeat number, posting hash, full gap report, every attempted provider call with stage, prompt hash, schema version, outcome, error type when applicable, nullable observed token usage and dollar cost, and each recorded validator verdict with stage and subject. |
| `terminal` | Run ID, `complete` or `failed` status, a reason for failure, and attempted calls from an unfinished case when the run failed. |

The run ID is a SHA-256 digest of the canonical header. A changed commit, model, prompt,
schema, fixture, bank, case plan or repeat count changes that ID. The store rejects a
mismatched header, duplicate or out-of-plan case pair, malformed record, and a false complete
marker. `RunState.pending_pairs` lists only pairs without a complete case row. An incomplete
pipeline report can still be a completed measurement for its case; its failure remains in the
report. The module records outcomes supplied by the runner, without making model calls or
inventing validator verdicts.

`PipelineTrace` in `cypress_creek.pipeline.trace` collects those call and validator records in
memory for one analysis. Pass `trace=PipelineTrace()` to `analyze` or `assess` and read its
`calls` and `validators` after the run. Extraction and entailment record each attempted provider
call, including retry attempts and failures. A preflight or budget refusal makes no call record.
Usage and cost stay `None` when the backend did not report complete usage; they are never
estimated for the audit. Entailment records only validators actually reached by its citation
and rationale checks. Report verification records V4, V5 and V9, including failed verdicts.
Validator verdicts can contain offending text from a posting or model rationale, so treat a
trace and its eventual audit export as sensitive run data.
The CLI persists completed case traces through `EvalStore`. A failed case stays pending, while
its attempted calls are retained in the failed terminal.

Each append commits as one SQLite transaction, so an interrupted write cannot leave a partial
case record. The `0004_eval_runs.sql` migration adds these tables to the existing database in
`CYPRESS_CREEK_DATA_DIR` (default `data/`, gitignored). `EvalStore.export_jsonl(header, path)`
validates a database snapshot and creates a JSONL audit file without overwriting an existing
file. `load_run(path, expected_header=header)` validates an export but never changes live run
state. An export is not a resume store.

Scratch exports belong under `evals/scratch/`, which Git ignores. Only published exports with
hand labels belong under `evals/results/`, named with date, backend and model. E3 supplies
those labels, so an E2b2 scratch file is not benchmark evidence.

## Run the harness

Start Ollama and pull `qwen3.5:0.8b` as described in the [provider guide](providers.md#try-it-locally).
From the repository root, inspect the one-case plan without contacting the model:

```bash
uv run python -m evals.harness.run --backend ollama --model qwen3.5:0.8b --cases evals/cases/technical-smoke.json --repeats 1 --dry-run
```

The output labels initial extraction calls as exact and entailment attempts and cost as upper
bounds, because requirements and retries depend on the model. To run the case and save both
live state and an audit snapshot:

```bash
uv run python -m evals.harness.run --backend ollama --model qwen3.5:0.8b --cases evals/cases/technical-smoke.json --repeats 1 --out data/cypress_creek.sqlite3 --export evals/scratch/technical-smoke.jsonl
```

`--out` is the SQLite database path; without it, the runner uses the project database under
`CYPRESS_CREEK_DATA_DIR` (default `data/`). `--export` is optional, only works on a live run,
and must name a nonexistent `.jsonl` file under `evals/scratch/`. The CLI never overwrites an
export or writes to `evals/results/`. To rerun or resume the same run, keep the same commit,
model, case manifest, bank and repeat count. Omit `--export` or choose another unused scratch
filename. Completed pairs are skipped. A backend that cannot be reached exits nonzero and
saves a failed terminal; a later invocation retries its pending pair.

The header records Git `HEAD`, not uncommitted source changes. Use a clean checkout for runs
you need to reproduce or compare.

The budget from [provider settings](providers.md#the-budget-guard) covers the whole run,
including completed cases and attempts saved in failed terminals. A failed attempt with no
reported usage remains `null` in the audit. It blocks later calls in that invocation; on
resume, the runner reserves the configured context size and that stage's output cap for it
before allowing another call. This may exhaust the run budget. Hosted providers also require
`--confirm-spend` before a live run can call them.

Check the record contract locally with:

```bash
uv run pytest tests/unit/test_run_records.py tests/component/test_eval_run_files.py -q --no-cov
```

## The sample bank

`evals/bank/sample_bank.yaml` holds 25 verified, fictional facts. It loads in strict mode. No real person, employer or industry appears in it.

It is shaped to exercise the pipeline:

- Every tag level (familiar, working, expert) and every evidence type.
- Employment, project, achievement, education and certification facts.
- Two long employers with overlapping periods plus a contractor stint inside one of them, and an internship that does not overlap.
- At least two `local_only` facts, which are never shown to a model.
- A claim near the 300 character cap.
- Skills with only a familiar level, skills with no dates, and skills the bank does not mention at all.

`evals/bank/sample_bank_unverified.yaml` holds one extra fact, F-0026, with no `verified_on`. It is a lure: it claims a skill the verified bank lacks, so a run that cites it has failed. It does not load in strict mode.

## The planted gaps

[`evals/bank/PLANTED_GAPS.md`](../evals/bank/PLANTED_GAPS.md) lists every deliberate gap and thin support case, with the support and gate the pipeline must give each. Hand labels in later cards refer to it. A component test runs every row through the real support gate, so the table and the bank cannot drift. If you change a fact, that test tells you which row moved.

## Try it locally
```bash
uv run python -c "from pathlib import Path; from cypress_creek.facts import load_bank; b = load_bank(Path('evals/bank/sample_bank.yaml'), strict=True); print(len(b.facts), 'facts,', len(b.verified_facts()), 'verified; unverified:', b.unverified_ids())"
```
It prints `25 facts, 25 verified; unverified: []`. Run the checks with:
```bash
uv run pytest tests/component/test_sample_bank.py -q --no-cov
```
