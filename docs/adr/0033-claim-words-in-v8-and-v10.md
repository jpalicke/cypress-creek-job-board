# ADR 0033: Claim words in V8 and V10, strict for drafts

Status: proposed (issue #131, pending PR review)

## Decision

- Four classes of unsupported draft claim passed every check (issue #131): a quantity word ("for a decade"), an invented result ("doubling revenue"), rank inflation ("senior staff") and negation ("Never led"). They are now caught by small deterministic word lists in `validators/claim_words.py`, with no model in the loop.
- V8 also requires a quantity word (decade, dozen, couple, half, double, triple and so on, in any inflection) to be used by a cited fact or by the requirement text when one is passed. This applies everywhere V8 runs.
- V10 gets a strict form, `check_novel_terms(..., claim_words=True)`, which only drafts use. It flags a result, a rank or a negation that no cited fact makes, and a negation that a cited fact makes and the sentence drops. It stays off for entailment rationales, because a rationale may say "the facts do not show Kubernetes" and withholding those would change what a user sees for a legitimate reason.
- Words are matched whole, lower case, by group, so a paraphrase inside a group is fine ("cut" for "reduced", "doubling" for "doubled") and a hyphenated compound ("double-checked") is its own word. A fact's own claim, employer, role, issuer, tag names and tag levels count as the facts' words.
- No new validator id is added. The numbered set V1 to V14 is the spec's contract, and these checks are refinements of the numeric and novel term rules.

## Why

The posting is not a source for a draft and the model is not trusted, so every claim word must be backed by the cited facts. A word list is auditable, deterministic and testable with hostile and legitimate examples; a model judge would add a second untrusted component to the part that guards the core rule.

## Cost of a flag

A flag costs a person a look at a sentence, and `needs_human_review` is always true anyway. Tests pin legitimate paraphrases of a fact that must stay clean. The known price is false positives when an honest sentence swaps between groups (a fact says "reduced", the sentence says "improved") or uses a negation form the fact does not.

## Limits

The lists are finite. A result or rank word that is not listed ("spearheaded", "pioneered", "successfully"), meaning (the right words in the wrong relation), and citing an unrelated verified fact still pass. Growing the lists needs a hostile example and a legitimate paraphrase test for each addition. Claim words in entailment rationales are not checked.

See [validators.md](../validators.md#claim-words) and [pipeline.md](../pipeline.md#draft-help).
