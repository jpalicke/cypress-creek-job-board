# Gotchas

Lessons from actual corrections, with the rule and its reason. `CLAUDE.md` is the authoritative engineering policy; `docs/handoff.md` describes the workflow. Before recording another lesson, check whether one here already covers it. Update existing guidance instead of creating duplicate or contradictory rules.

## Git identity is the noreply address
Never commit with a personal email address. The repo identity is `user.name` "jpalicke" and `user.email` "13882087+jpalicke@users.noreply.github.com". Check `git config user.email` before the first commit in a clone.

Why: the first commit carried a personal address, which was publicly exposed; the commit had to be amended and force-pushed.

## Documentation ships with the change
Update documentation affected by a behavior change in the same PR. Do not defer necessary docs to a later PR. Check `README.md` status and "Try what exists" whenever user-visible behavior or run instructions change. For split work, each PR carries the documentation necessary for what it delivers.

Why: the README went stale across two cards, and a separate docs branch was rejected.

## Keep PRs reviewable
Aim for about 10 changed files, with 20 as a practical upper bound. Propose a split if a card will be substantially larger, but do not split a coherent fix merely to meet an arbitrary file count. Each split needs its own relevant documentation.

Why: B4 landed as a roughly 40-file PR that was difficult to review.

## Audit documentation affected by a change
Before reporting a card complete, check the documents that could plausibly be stale because of the change. Examples: README status and usage, the docs index and configuration lists, the codebase layout and flow, contributor commands, the owning doc, and ADRs for significant design decisions. Run new or changed commands; verify existing commands when the change could affect them. Do not reread every document or run every documented command for unrelated edits.

Why: on B5, weights configuration and the PR-size rule were omitted from several relevant docs until Joe P asked whether they were current.

## Test changed behavior before implementation
For new or changed observable behavior, first write or adjust a relevant test and confirm it fails for the right reason. This applies to behavioral changes discovered midway through a card. If an existing failing test already demonstrates the requirement, it suffices; do not add another just to follow a ritual. Pure refactoring does not require a new failing test when existing tests protect the behavior. Keep tests focused on distinct defects, and consolidate redundant cases.

Why: on B6a, the implementation was rewritten for full Unicode confusables data before the tests were updated. The failure was changing behavior without first establishing the expected behavior in tests, not an insufficient number of tests.

## Post the merge summary on the issue too
When asking Joe P to merge, post the same concise summary as a comment on the card's issue so the ticket records the completed work.

Why: Joe P requested this on B6a.

## Treat truncated token counts as truncated counts
Never infer the full input token count from Ollama's `prompt_eval_count` when it matches a truncation signature. Keep a posting character cap separate from the configured model context and verify actual fit with the provider guard.

Why: a 50,000-character posting returned 16,386 prompt tokens at `num_ctx` 32,768 because Ollama had already truncated its input; that number did not measure the full posting.

## Verify merge conflict resolution
After resolving a merge, search every touched file for conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) before `git add`. A resolver script that reports a failure must stop the commit; do not chain the commit so it runs after a failed check.

Why: an earlier correction identified the risk of committing unresolved conflict markers or continuing after a failed resolver. The original record did not include a separate incident description.

## Keep live evaluation state in SQLite
Store resumable evaluation runs in SQLite transactions. Preserve each record's JSON payload there; write JSONL only as an audit export. Never use an exported file as the live state store.

Why: direct JSONL append can leave a torn final row, while rewriting the whole file adds recovery work already handled by SQLite transactions.

## Retrospective tests must demonstrate effectiveness
When writing tests for behavior that already exists, deliberately introduce a representative defect in each distinct behavior being protected, verify that the relevant test detects it, then restore the implementation. Record what was checked in the PR, including which tiers would and would not detect important failures. Do not mutate every assertion or minor implementation detail, and do not repeat this exercise when a test already demonstrated a genuine red-green cycle.

Why: on H3, deliberate wrong assertions made tests appear red even though the adapter already existed. Those failures did not demonstrate that the tests could catch real defects such as lost unescaping, incorrect 404 mapping, or a missing budget check. Live feeds also did not exercise hostile-input handling.
