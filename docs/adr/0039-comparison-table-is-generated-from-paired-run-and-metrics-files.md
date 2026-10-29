# ADR 0039: The comparison table is generated from paired run and metrics files, and CI checks it is current

Status: accepted (card E7)

## Context

The published comparison of local and hosted backends must be reproducible, and a hand edited table drifts from its data. The table also has to say under which conditions each row was produced, and never show a missing run as a zero.

## Decision

- **A script owns the table.** `evals/harness/table.py` writes `docs/evals-results.md` and a marked block of the README from one rendering function. `--check` regenerates both and fails when the committed text differs. The deterministic workflow runs the check, so a run file added without regenerating the table fails CI.
- **Each row needs two files.** The scorer's metrics JSON has the numbers and the run export has the header (commit, prompt hashes, fixture set hash) and the recorded calls (cost, schema failures). They are paired by run id and a missing half is an error, so no row is built from part of its data. The scorer's output was not changed for this.
- **A target list is data.** `evals/backends.yaml` names the backends the table must show and the match rule (exact model, else any model). LM Studio and OpenAI are both `openai_compatible` runs and are told apart by the model, which the list owns.
- **Conditions are a column.** Rows are grouped by the pair (combined prompt hash, fixture set hash). More than one group means the rows are marked "not comparable" and a note says why.
- **Missing is never zero.** A backend with no run says `not run`. A metric nobody measured (E6 score shift before the injection corpus exists) says `not run`. Median latency says `not recorded`, because the run records carry no timing. Cost for a repeat with any call of unknown cost is left out of the mean.
- **The E8 schema failure rate is the share of provider calls that ended in `SchemaViolation`.** It is computed from the run export per repeat, with the worst repeat being the highest.

## Consequences

- Adding timing to the run record (a follow-up) turns the latency column on without changing the table's shape.
- The injection corpus (E5) only needs to write a `score_shift` metric for the E6 column to fill in.
- The first published run (E8) is: score, copy the pair into `evals/results/`, regenerate, commit.

## Alternatives considered

- Put the header and cost fields into the scorer's metrics JSON so the table reads one file. Rejected here to leave the scorer (card E4) unchanged; it would be a reasonable later simplification.
- Hand maintain the table with a CI check on its numbers. Rejected: the point is that no human edits it.
