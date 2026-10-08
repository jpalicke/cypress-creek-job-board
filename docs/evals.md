# Evals

The eval harness measures the pipeline against a fixed, fictional fact bank. The run record
format is available now. The runner, postings and hand labels come in later cards.

## Run record format

`cypress_creek.eval_records` defines version 1 of the JSONL format. One file starts with a
`header` row, contains one `case` row for each completed case and repeat, and ends with a
`terminal` row when the run succeeds or fails. A file without a terminal is incomplete. A
`failed` terminal carries a reason and can be followed by later case rows and a `complete`
terminal when the same run resumes. A `complete` terminal requires every planned pair.

| Row | Required audit data |
| --- | --- |
| `header` | Git commit, provider, exact model, prompt hashes and schema versions by stage, fixture set hash, bank hash, ordered case IDs and repeat count. `format_version` is 1. |
| `case` | Run ID, case ID, repeat number, posting hash, full gap report, every recorded provider call with stage, prompt hash, schema version, token usage and dollar cost, and each recorded validator verdict with stage and subject. |
| `terminal` | Run ID, `complete` or `failed` status, and a reason for failure. |

The run ID is a SHA-256 digest of the canonical header. A changed commit, model, prompt,
schema, fixture, bank, case plan or repeat count changes that ID. `load_run` rejects a
mismatched header, duplicate or out-of-plan case pair, malformed row, and a false complete
marker. `RunState.pending_pairs` lists only pairs without a complete case row. An incomplete
pipeline report can still be a completed measurement for its case; its failure remains in the
report. The module records outcomes supplied by the runner, without making model calls or
inventing validator verdicts.

Scratch runs belong under `evals/scratch/`, which Git ignores. Only published runs with
hand labels belong under `evals/results/`, named with date, backend and model. E2b adds the
CLI that fills these records from real providers. E3 supplies the labels, so no E2a file is
benchmark evidence.

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
