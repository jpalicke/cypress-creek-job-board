# ADR 0001: Fact bank enums and defaults

Status: accepted (Joe P, card B1)

## Decision
- `kind`: employment, project, education, certification, achievement.
- Tag `level`: familiar, working, expert. The design fixes only that `familiar` caps support at partial (card B2).
- `evidence.type`: employer_doc, repo, certificate, public_url, self_attested.
- `share` has two values, `shareable` and `local_only`, and defaults to `local_only`.
- Unknown fields on any model are rejected (typo protection and no smuggled data).
- Anchors and aliases in the bank YAML are refused, and the file size is capped at 1 MB.
- Default personal bank location is `facts.private/bank.yaml` (gitignored), overridable with the `CYPRESS_CREEK_BANK` environment variable.

## Why
`local_only` is the safer default: a fact is only sent to a hosted backend when its owner opts in. Closed enums make every value known to validators. Aliases are refused because a bank has no use for them and they allow expansion attacks.
