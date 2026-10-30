# Gotchas

Lessons from actual corrections, with the rule and its reason. `CLAUDE.md` is the authoritative engineering policy; `docs/handoff.md` describes the workflow. Before recording another lesson, check whether one here already covers it. Update existing guidance instead of creating duplicate or contradictory rules.

## Git identity is the noreply address
Never commit with a personal email address. The repo identity is `user.name` "jpalicke" and `user.email` "13882087+jpalicke@users.noreply.github.com". Check `git config user.email` before the first commit in a clone.

Why: the first commit carried a personal address, which was publicly exposed; the commit had to be amended and force-pushed.

## Documentation ships with the change
Rule: `CLAUDE.md` (Documentation).

Why: the README went stale across two cards, and a separate docs branch was rejected.

## Keep PRs reviewable
Rule: `CLAUDE.md` (Development approach).

Why: B4 landed as a roughly 40-file PR that was difficult to review.

## Audit documentation affected by a change
Rule: `CLAUDE.md` (Documentation), before reporting a card complete.

Why: on B5, weights configuration and the PR-size rule were omitted from several relevant docs until Joe P asked whether they were current.

## Test changed behavior before implementation
Rule: `CLAUDE.md` (TDD and test selection).

Why: on B6a, the implementation was rewritten for full Unicode confusables data before the tests were updated. The failure was changing behavior without first establishing the expected behavior in tests, not an insufficient number of tests.

## Post the merge summary on the issue too
Rule: `CLAUDE.md` (Development approach), so the ticket records the completed work.

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
Rule: `CLAUDE.md` (TDD and test selection). Introduce one representative defect per distinct protected behavior, not one per assertion or implementation detail.

Why: on H3, deliberate wrong assertions made tests appear red even though the adapter already existed. Those failures did not demonstrate that the tests could catch real defects such as lost unescaping, incorrect 404 mapping, or a missing budget check. Live feeds also did not exercise hostile-input handling.

## Windows scratch paths and escapes
Harmless CRLF warnings may appear on Windows. Keep generated scratch files in a short path such as `C:/Temp/ccb`, and use an editor tool for files with backslash escapes rather than shell heredocs.

Why: the original record did not include a separate incident description.

## Commands for Joe P are PowerShell
Joe P runs commands in Windows PowerShell 5.1. Give Windows paths (`C:\...`), `;` between commands instead of `&&`, and cmdlets such as `Copy-Item` and `Remove-Item`, not Git Bash syntax.

Why: a set of handoff commands written as `/c/...` paths chained with `&&` all failed in his terminal.
