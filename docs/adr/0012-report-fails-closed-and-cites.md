# ADR 0012: The gap report fails closed and every claim cites

Status: accepted (Joe P, card D5)

## Decision
- `build_report` computes the score itself from the final matches, so a score that disagrees with the rows cannot be passed in.
- A failed extraction gives an incomplete report with no rows, no score and the reason.
- A requirement whose entailment call failed keeps its rule ceiling in the score. Its row is flagged `not_model_checked`, it cites the candidate facts its ceiling rests on, and the whole report is `incomplete` with a reason naming those requirements. The score is not presented as a full run.
- Hitting the requirement cap does not make a report incomplete. It is shown as `not_assessed_count`. Cue coverage (V13) is a later card.
- No requirements gives a complete report with no score, never 100.
- `build_report` ends with `verify_report`: V4 and V5 over every cited id, and V9 over every row whose support is not none. A failure raises `ReportRefused` and no report is returned.
- The report is data first. The text view flattens posting and model text to one line, and HTML escaping belongs to the future UI.
- One stage numbering: 0 normalize, 1 extract, 2 retrieve, 3 entail, 4 score and report, 5 render. Drafting (spec stage 6) is post v1.

## Why
A partial run shown as complete, or a claim with no citation, is exactly the failure the product exists to prevent. Building the checks into the one function that makes a report means no caller can skip them.

## Limits
- A `not_run` requirement may be over or under stated, because its support is the rule ceiling and nobody second checked it. The report says so.
- V9 checks that a claim cites something, not that the citation fits. V7, V8 and V10 on the rationale and the entailment verdict carry that load.
