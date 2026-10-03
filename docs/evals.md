# Evals

The eval harness measures the pipeline against a fixed, fictional fact bank. This page covers the sample bank. Postings and hand labels come in later cards.

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
