# ADR 0026: Draft help checks each sentence and can only show data

Status: proposed (D7, pending PR review). The number is provisional and follows merge order.

## Decision

- Draft help is a paraphrase of supplied verified facts, one call per requirement, returned as sentences that each cite fact IDs (`DraftOutput`). It is optional and sits after the gap report.
- Every sentence is checked alone, against only the facts it cites: V4, V5, V6, V7, V8, V9 and V10. No check short circuits, so the record on the sentence is complete. V2 does not apply because a draft quotes no posting span.
- V4 is checked against the facts that were supplied to the model, not the whole bank. A real, verified fact the model was never shown is therefore not citable. Otherwise a model could cite a fact it only knows from outside the prompt, or one filtered out for a hosted backend.
- A failing sentence stays in the result with its verdicts and is rendered as `! NOT VERIFIED (V8: ...)`. Only `clean_sentences` is fit to copy. We keep failures visible, rather than removing them, so the person sees what the model tried and why it was refused. Model text is flattened to one line so it cannot forge a marker or a banner.
- A requirement with no candidates, or whose support ceiling is `none`, is answered with `no verified fact supports this` and advice to add a verified fact. No model call is made, so a gap cannot be papered over.
- `needs_human_review` is a literal `True` on every `Draft`. There is no send, copy, apply or file path in the module, and a unit test audits its imports.

## Why

The product's rule is that no output asserts a claim without a verified fact behind it. Checking each sentence on its own gives a precise reason for each refusal, and showing failures with a marker is safer than silently dropping them (a person never wonders what was hidden) while staying distinguishable from clean text.

## Limits

The checks are heuristics. V10 can miss an invented common word, and V8 cannot tell a correct number attached to the wrong thing. A passing draft is a candidate paraphrase for a person to read, not a proven statement. The live test uses the tiny CI model, so it proves the plumbing and the verdicts, not draft quality.

See [pipeline.md](../pipeline.md#draft-help).
