# ADR 0032: How the scorer matches rows to labels and defines the E1 to E4 metrics

Status: accepted (pod decision under Joe P's delegation, card E4; his review pending)

## Decision
- A report row matches a labeled requirement when the overlap of their posting spans is at least half of their union. Matching is one to one, largest overlap first, ties by label then row order.
- `ReportRow` records the requirement's `span` and `raise_attempted`. The scorer reads them and never searches for row text. Both default for older stored reports, and the scorer refuses a row without a span.
- Each repeat is scored alone from pooled counts. A run reports every repeat's value, the mean and the worst (lowest where higher is better, highest where lower is better). A repeat missing any planned case is not scored. A metric nobody measured is `not_run`.
- Gap recall is over planted gaps that were extracted. A planted gap that was never extracted is a recall loss, shown in the mismatch view, but it is not counted as a missed gap, because the report asserted nothing about it. A planted gap reported as strong is a missed gap and is listed with the fact ids it cited.
- Grounding violations are counted per violation (a fabricated id, an unverified citation, an uncited claim), against the bank the run used, and reported per 100 reports.
- The scorer refuses a run whose bank hash is not the bank given, a case with no fixture, and a posting that differs from its fixture. It calls `require_committed_labels` for every fixture it uses.
- The metrics JSON is deterministic: no timestamps, a stable key order, file name `<backend>-<model>-<run id prefix>.json`, and an existing file is never overwritten. A backend with no run gets `<backend>-not-run.json`.

## Why
- Intersection over union rewards an exact span and still accepts a trimmed or extended one, so a model that quotes a slightly different part of the same sentence is not scored as missing it. A looser rule would let a one word row match a whole sentence.
- Attempted raises cannot be recovered from the final report, because the clamp has already removed them. Recording the flag on the row is the smallest change that lets E2 count them before the clamp.
- Counting an unextracted gap as a missed gap would blame the entailment and report stages for an extraction miss and would hide which stage failed.

## Limits
- The overlap threshold is a judgment call. A different threshold changes recall and precision, so it is a constant in `evals/harness/metrics.py` and the value is part of the published definition.
- `downgrade_accuracy` checks only whether the support went below the ceiling, not whether it landed on the labeled level.
- No fixture is run through the real runner yet, so the only scored runs are built from labels (synthetic) and the small live test. Nothing here is a benchmark result.
