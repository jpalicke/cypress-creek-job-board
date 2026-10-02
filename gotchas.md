# Gotchas

Strict rules added after corrections. Format: the rule, then why.

## Git identity is the noreply address
Never commit with the personal gmail address. The repo identity is user.name "jpalicke" and user.email "13882087+jpalicke@users.noreply.github.com". Check `git config user.email` before the first commit in any clone.
Why: the first commit carried the personal address, which is public in a public repo and attracts spam. It had to be amended and force pushed.

## Docs ship in the same PR as the code
Documentation is updated in the same PR as the implementation. Never propose a later docs-only PR. Splitting needs Joe P's explicit approval. Check README.md status and "Try what exists" on every card, not only the doc the card owns.
Why: the README went stale across two cards, and the proposed fix was a separate docs branch, which was rejected.

## Keep PRs small
Aim for at most 10 changed files per PR, hard cap 20. If a card will exceed about 10 files, propose a split into sequential PRs (each with its own docs) before starting.
Why: B4 landed as a roughly 40 file PR that was too big to review.

## Audit every doc before reporting a card done
Before reporting, grep README.md, docs/README.md, docs/codebase.md, docs/contributing.md and the owning doc for each new module, config file, command, rule and ADR, and update every place that should mention it (layout, flow, "Ideas to know", "How to change X", config listings, index, process rules). Run each doc command. Stale docs are a shame upon the house.
Why: on B5 the weights config and the PR size rule were missing from several docs until Joe P asked whether all docs were current.
