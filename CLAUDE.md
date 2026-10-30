# Cypress Creek Job Board: working agreements

## Who we are
Assistant: Claude. Human: Joe P (Palicke, JP).
We are coworkers. JP makes the final call. Be direct, challenge assumptions with evidence, and prefer useful progress over ceremony.

## Nonnegotiable product guarantees
- Nothing the tool outputs may assert a claim that is not backed by a verified fact ID in the fact bank. Deterministic validators enforce this, never prompting alone.
- No auto apply, auto send, or outward posting behavior. A human reviews every draft.
- Treat all external input as hostile, including postings, PDFs, feeds, and model output.
- The model has no tools and no side effects. Its output is untrusted data until validated.
- Send only posting text and relevant verified facts to a model.
- Secrets belong in environment variables or a gitignored `.env`, never in commits.
- Never disable functionality, weaken validation, or bypass a failing check to make a task appear complete.

## Development approach
- Choose effort based on risk and complexity. For a straightforward, localized change, implement directly with focused verification. For ordinary features, use focused TDD and a concise self-review. For changes to claim validation, fact provenance, security boundaries, provider contracts, persistence, or major architecture, use stronger adversarial testing and independent review.
- Use subagents only for truly parallel, independent work, never merely because a card or phase exists. The main agent passes the needed file excerpts and line ranges in the prompt, so a subagent does not reread `gotchas.md`, `docs/handoff.md`, or whole source files. Keep delegated tasks bounded. Use less expensive subagent models for routine tasks when the environment supports it; do not assume model selection is available.
- Avoid repeated planning, rereading unrelated documents, or spawning additional reviewers without a concrete reason. If a review finds a real defect, fix it; do not expand scope to unrelated improvements.
- A new contributor starts with `docs/handoff.md` for the card routine, but where older process instructions conflict with this file, follow this file and flag the discrepancy for correction.
- Work on a branch per task, open a PR, and merge only after Joe P approves. No worktrees unless Joe P explicitly approves an exception, including when a third-party skill expects one.
- Keep PRs reviewable: aim for about 10 changed files, with 20 as a practical upper bound. Propose a split before exceeding that bound. Do not split a coherent fix solely to hit an arbitrary number.
- When asking for a merge, post the same concise summary on the card's issue. Do not auto-merge or poll CI continuously.
- Never bypass hooks with `--no-verify`, `--no-hooks`, or equivalent flags. Diagnose and fix failures.
- Commit messages and PR text have no attribution lines. Do not use em dashes in code, comments, documentation, commits, or PR text.

## TDD and test selection
- Use red-green-refactor for new or changed observable behavior. First write or adjust a test that demonstrates the missing or incorrect behavior, run it, and confirm that it fails for the right reason. Then make the smallest meaningful implementation change and refactor with tests green. This applies to behavioral changes discovered midway through a card.
- A single failing test may justify multiple implementation edits. An existing failing test can satisfy the test-first requirement; do not create a new test for every branch, helper, or edit. Pure refactoring does not require new failing tests if existing tests protect the behavior.
- Before adding a test, ask what distinct realistic defect, requirement, boundary, regression, or failure mode it would detect that the existing suite would miss. Prefer representative equivalence classes, meaningful boundaries, and parameterized cases instead of exhaustive combinations.
- Consider unit, component, integration, and e2e tests, but do not require new tests at every tier for each card. Test at the lowest level that meaningfully proves the behavior. Add a higher-level test when it verifies a distinct integration boundary or user-visible guarantee.
- Consolidate redundant tests during refactoring. Do not test private implementation steps solely because they exist. Do not weaken independent safety, security, provenance, or regression tests merely to reduce test count.
- Keep the existing 80% unit-plus-component coverage gate in pre-commit and CI. Coverage helps identify gaps; it is not a target for test multiplication. If the gate leads to low-value tests, explain the problem rather than fabricating scenarios or silently changing the threshold.
- No mock mode, fake providers, or stubbed HTTP in application call paths. Recorded real outputs and hostile handwritten inputs may be used as test inputs. Preserve existing test-environment boundaries; do not quietly turn a live integration check into a stubbed success.
- When a required backend is unreachable, fail loudly rather than silently skip. Respect existing explicit offline/live test separation.
- For tests added after their implementation already exists, verify effectiveness with a representative deliberate fault in the relevant behavior, then restore it. Record in the PR what was checked, including which tiers would and would not detect important failures. Do not perform a second mutation exercise for a test that already demonstrated a genuine red-green cycle.
- Keep test output clean. Capture and assert expected error logs.

## Verification and review
- While developing, run the smallest relevant tests, formatting, and static checks needed for fast feedback. Avoid repeatedly running the entire suite after unrelated small edits.
- Before reporting a card complete, run the repository's required checks, including strict type checking, linting, tests, coverage, and hooks. Use the commands in `docs/handoff.md` and preserve CI and live-test requirements. Do not claim a test or check passed unless it ran and passed; report blocked or unavailable checks explicitly.
- Review the final diff for correctness, unnecessary test duplication, unintended scope, and security regressions. Use an independent reviewer for high-risk or unusually complex changes; otherwise a focused self-review is sufficient.
- Report briefly: what changed, key tests and checks, relevant risks or limitations, and what requires Joe P's decision.

## Code
- Every code file starts with two comment lines, each starting with `ABOUTME: `.
- Simple, readable, maintainable code beats clever code. Match surrounding conventions.
- Use evergreen names, never `new`, `improved`, or `enhanced` as version labels.
- Maintain one source of truth. Do not duplicate state to solve a display problem.
- Do not remove a comment unless it is provably false. Comments describe the code as it is, not its history.
- Keep changes within the task. File an issue for unrelated findings instead of implementing them.
- When renaming, check calls, types, string literals, dynamic imports, re-exports, and tests.

## Documentation
- Update documentation affected by the change in the same PR. Installation, setup, configuration, commands, user-visible behavior, and architecture must remain accurate and runnable from `README.md` and `docs/`.
- Find stale docs by grepping `README.md`, `docs/`, and `gotchas.md` for the names, commands, flags, and paths the change touched, then read and edit only the matching sections. Never read a whole document to audit it, and do not execute every documentation command for an unrelated edit. Run new or changed commands, and verify critical existing commands when the change could affect them.
- Document significant design decisions in an ADR when warranted. Do not create process documents or ADRs for trivial implementation details.
- If a card must be split, each PR includes the documentation necessary for its own delivered behavior.

## Project details
- API port: 5309. Vite development server: 5150. Infrastructure keeps its defaults (for example, Ollama 11434).
- Do not mention any specific employer or industry in the repo, README, or fact bank. Public third-party postings used as evaluation fixtures are exempt if listed in NOTICE with source and takedown contact.

## Lessons and corrections
- `gotchas.md` records generalizable mistakes and their reasons, not an ever-growing collection of duplicate commands. After a correction, check whether an existing rule already covers it. Revise that rule when possible; add a new rule only for a genuinely new recurring failure mode.
- Preserve the underlying lessons in `gotchas.md`, especially test-first behavioral changes and effectiveness checks for retrospective tests. If its older wording conflicts with this agreement, flag and reconcile it rather than following both conflicting instructions.
