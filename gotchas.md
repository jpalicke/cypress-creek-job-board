# Gotchas

Strict rules added after corrections. Format: the rule, then why.

## Git identity is the noreply address
Never commit with the personal gmail address. The repo identity is user.name "jpalicke" and user.email "13882087+jpalicke@users.noreply.github.com". Check `git config user.email` before the first commit in any clone.
Why: the first commit carried the personal address, which is public in a public repo and attracts spam. It had to be amended and force pushed.

## Docs ship in the same PR as the code
Documentation is updated in the same PR as the implementation. Never propose a later docs-only PR. Splitting needs Joe P's explicit approval. Check README.md status and "Try what exists" on every card, not only the doc the card owns.
Why: the README went stale across two cards, and the proposed fix was a separate docs branch, which was rejected.
