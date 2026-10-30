# ADR 0039: The comparison table is generated from paired run and metrics files, and CI checks it is current

Status: accepted (card E7)

## Context

The published comparison of local and hosted backends must be reproducible, and a hand edited table drifts from its data. The table also has to say under which conditions each row was produced, and never show a missing run as a zero.

## Decision

- **A script owns the table.** `evals/harness/table.py` writes `docs/evals-results.md` and a marked block of the README from one rendering function. `--check` regenerates both and fails when the committed text differs. The deterministic workflow runs the check, so a run file added without regenerating the table fails CI.
- **Each row needs two files.** The scorer's metrics JSON has the numbers and the run export has the header (commit, prompt hashes, fixture set hash) and the recorded calls (cost, schema failures). They are paired by run id and a missing half is an error, so no row is built from part of its data. The scorer's output was not changed for this.
- **The table scores again and refuses a mismatch.** For every pair the table loads the run file, requires the committed labels (the same check the scorer makes), scores it with the E4 scorer (`score.rescore`, the function the scorer CLI uses) and compares the result with the metrics file. Any difference is an error naming the file, so a hand edited or stale metrics file cannot reach the table. `--fixtures`, `--bank` and `--injection-fixtures` point at other inputs for tests.
- **E6 is the worst class and the disrupted count.** The two E6 columns read the `injection` results of the metrics: the largest `max_abs_shift` over the attack classes (mean and worst over repeats, so opposite shifts cannot cancel) and the number of attacked cases whose report was disrupted, counted over every scored repeat (`injection_disrupted`). A run with no injection cases says `not run`.
- **A target list is data.** `evals/backends.yaml` names the backends the table must show and the match rule (exact model, else any model). LM Studio and OpenAI are both `openai_compatible` runs and are told apart by the model, which the list owns.
- **Conditions are a column.** Rows are grouped by the pair (combined prompt hash, fixture set hash). More than one group means the rows are marked "not comparable" and a note says why.
- **Missing is never zero.** A backend with no run says `not run`. A metric nobody measured (E6 for a run with no injection cases) says `not run`. Median latency says `not recorded`, because the run records carry no timing. Cost for a repeat with any call of unknown cost is left out of the mean.
- **The E8 schema failure rate is the share of provider calls that ended in `SchemaViolation`.** It is computed from the run export per repeat, with the worst repeat being the highest.

## Consequences

- Adding timing to the run record (a follow-up) turns the latency column on without changing the table's shape.
- Building the table costs a re-score of every published run, which is cheap and deterministic.
- The first published run (E8) is: score, copy the pair into `evals/results/`, regenerate, commit.

## Alternatives considered

- Put the header and cost fields into the scorer's metrics JSON so the table reads one file. Rejected here to leave the scorer (card E4) unchanged; it would be a reasonable later simplification.
- Hand maintain the table with a CI check on its numbers. Rejected: the point is that no human edits it.
