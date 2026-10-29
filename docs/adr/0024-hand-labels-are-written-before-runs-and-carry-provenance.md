# ADR 0024: Hand labels are written before any run, carry their provenance, and are validated against the posting and the bank

Status: accepted (Joe P delegated the labeling to the pod, card E3). Joe P reviews the labels and may order changes.

## Context

The eval is only honest if the labels cannot have been fitted to a backend. Card E3 first asked for Joe P to write every label himself. Joe P then delegated the labels to the pod and said he will review them. Real postings also change or close, so the fixtures must record where they came from and what they replaced.

## Decision

- **Labels are written from the posting text and the bank alone, before any run.** Provenance is part of every `labels.yaml`: who labeled it, `review` (`pending` until Joe P signs it off), the date, and `model_output_used`, which the schema only accepts as `false`. The harness refuses a case whose labels are not tracked and identical to the committed file (`require_committed_labels`), so a label edit has to be a commit that precedes any run record.
- **Importance is the human reading of the posting, not the cue rule.** A "What you'll bring" list is `required` even where V3 would say `unspecified`. The scorer must compare with that in mind. The alternative, following V3, would make most labels `unspecified` and importance agreement meaningless.
- **Status follows support.** `expected_status` is `gap` unless support is strong, the same rule the report uses for its gap list. The validator enforces it, so a label cannot say "supported" for a partial result.
- **Labels may cite only verified, shareable facts.** A local only fact is never shown to a model, so it cannot be expected support. A planted gap reference must agree with its `PLANTED_GAPS.md` row in kind, term, years, issuer and support.
- **Every cue sentence is listed.** Each sentence in a posting that holds a cue word is labeled `covered` or `not_a_requirement`, so V13 results can be scored.
- **Fixtures sit in `evals/fixtures/<ats>-<job id>/`.** The ATS prefix lets later cards add `injection/` and `pdf/` beside them without being mistaken for postings. `meta.yaml` holds the source, retrieval date, hash and, for a replacement posting, the ID it replaces and why. The hash is the SHA-256 of the exact `posting.txt` text, which must already be normalized.
- **A replacement for a closed posting comes from the same board.** The reason is recorded in `meta.yaml`.

## Consequences

- Joe P can change any label. The fix is an edit and a commit, and the earlier run files stay in the record under the older fixture and label state.
- Importance agreement and the tag gate will disagree on purpose for some labels. Those disagreements are listed in `docs/e3-label-decisions.md`.
- The fixture set hash covers posting text only. Labels are not hashed because the scorer reads them at scoring time, and run files record the commit.

## Alternatives considered

- Joe P writes every label by hand. Rejected by Joe P's delegation.
- Follow V3 for importance. Rejected, see above.
- Hash labels into the fixture set hash. Rejected: a label fix would change every run identity even when the pipeline input is unchanged.
