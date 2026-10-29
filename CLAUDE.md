# Cypress Creek Job Board: working agreements

## Who we are
Assistant: Claude. Human: Joe P (Palicke, JP).
We are coworkers. JP is the boss but we are not formal. Push back with evidence.

## The one rule that matters
Nothing the tool outputs may assert a claim that is not backed by a verified fact ID
in the fact bank. This is enforced by deterministic validators, never by prompting.
No auto apply. Ever. A human reviews every draft.

## How we work
- TDD. Write a failing test, see it fail, write the minimum code, see it pass, refactor. This applies to every design change mid card too: change the tests first and watch them fail before touching the implementation.
- When asking Joe P to merge, post the same summary as a comment on the card's issue.
- Before reporting a card done, audit every doc (docs/handoff.md has the list) and run each doc command.
- A new contributor or assistant starts at docs/handoff.md, which is the full card routine.
- Branch per task. Open a PR. Merge to main after review. No worktrees.
- PRs aim for at most 10 changed files, hard cap 20. Split big cards into several PRs, each with its own docs. Propose the split before starting.
- At most 5 files per phase. Run verification, then wait for approval.
- Development goes through the subagent development skill.
- Never use --no-verify, --no-hooks or any hook bypass. If a hook fails, fix the cause.
- Commit messages and PR text carry no attribution lines.
- Never use em dashes in any text, code comment or commit message.

## Code
- Every code file starts with a two line comment, each line starting with "ABOUTME: ".
- Simple, readable, maintainable beats clever. Match the style of the surrounding code.
- Evergreen names. Never "new", "improved", "enhanced".
- One source of truth. Never fix a display problem by duplicating state.
- Never remove a comment unless it is provably false.
- Comments describe the code as it is, not its history.
- Do not make changes unrelated to the task. File an issue instead.
- Never disable functionality to hide a bug. Fix the root cause.
- When renaming, search separately for calls, types, string literals, dynamic imports,
  re-exports and tests.

## Local docs
- Documentation always ships in the same PR as the implementation. Never defer docs to a later PR. Splitting needs Joe P's explicit approval.
- Every card leaves the local run docs current. Joe P must be able to clone, run and use whatever exists so far from README.md and docs/ alone, without asking. If a card changes how to install, run, test or configure anything, it updates those docs in the same PR.

## Testing
- Unit, component, integration and e2e all exist. No tier is ever marked not applicable.
- No mock mode, no fake providers, no stubbed HTTP in any call path.
  Recorded real outputs and hostile hand written outputs may be used as inputs.
- An unreachable backend fails the test loudly. Never skip.
- Coverage gate: 80% on unit plus component, in pre-commit and CI.
- Test output must be pristine. Expected error logs are captured and asserted.
- Do not report a task done until type check (strict), linters, and tests all pass.

## Security posture
- All external input is hostile: postings, PDFs, feeds, model output.
- The model has no tools and no side effects. Its output is data until validated.
- Send only the posting text and the relevant facts to any model.
- Secrets live in the environment or a gitignored .env. Never commit them.

## Ports
- API: 5309.  Vite dev server: 5150.
- Infrastructure keeps its defaults (Ollama 11434, and so on).

## Do not
- Mention any specific employer or industry in the repo, README or fact bank.
- Add auto apply, auto send or any outward posting behavior.
- Write implementation before the matching failing test exists.

## Mistakes log
After any correction, add the pattern to gotchas.md as a strict rule.
