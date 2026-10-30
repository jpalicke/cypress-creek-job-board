# Picking up a card (handoff guide)

This is the practical card routine. [CLAUDE.md](../CLAUDE.md) defines binding engineering and safety rules; [gotchas.md](../gotchas.md) records lessons from past mistakes. Read the relevant sections, not every document on every iteration. [codebase.md](codebase.md) explains the code.

## Who and what
- The owner is Joe P (Palicke, JP). Work as coworkers: raise concerns with evidence and ask when genuinely blocked.
- The product tailors a job application to a posting without inventing claims. Every output claim requires a verified fact ID, enforced by deterministic validators. No automatic applications or outward posting.
- The design linked from the issue board is the spec. Cards are GitHub issues with lane labels (`lane:B`, etc.). Closed issues are the source of truth for completion; do not maintain a duplicate status list.

## One-time setup
```bash
uv sync                          # Python 3.13 and pinned dependencies
uv run pre-commit install        # git hooks
git config user.name             # must be: jpalicke
git config user.email            # must be: 13882087+jpalicke@users.noreply.github.com
```
Never commit with a personal email address. Keep secrets in environment variables or a gitignored `.env`.

## The card routine
1. **Understand the card.** Check scope, dependencies, acceptance criteria, and relevant design documents. Use [lanes.md](lanes.md) to identify ready cards. Treat a card's suggested first failing test and test plan as guidance, not a mandate to add redundant tests. Identify the behavior and risks the tests need to establish.
2. **Choose a proportional workflow.** For small, localized changes, implement directly with focused verification. For ordinary changes, use focused TDD and a concise self-review. For claim validation, fact provenance, security boundaries, provider contracts, persistence, or major architecture, use stronger adversarial tests and independent review. Use subagents only as [CLAUDE.md](../CLAUDE.md) allows. Avoid unnecessary agent handoffs and review loops. Do not use worktrees without explicit approval, even if a plugin suggests them.
3. **Size and branch.** Aim for about 10 changed files per PR, with 20 as a practical upper bound; propose a split for work substantially beyond that, rather than splitting a coherent fix solely for a number. Each split delivers its own usable behavior and relevant docs. Start an up-to-date branch: `git checkout -b <card-id>-<short-name>`. No worktrees by default.
4. **Test meaningful behavior first.** For new or changed observable behavior, write or adjust a failing test and confirm it fails for the right reason before implementing. An existing failing test may be enough; do not create tests per helper, branch, or implementation edit. A pure refactor with already protective tests need not manufacture a new failing test. Select the testing tier that proves each risk; consider unit, component, integration, and e2e, but do not duplicate all scenarios across tiers. Preserve distinct provenance, security, and regression protections.
5. **Implement, then refactor.** Make the smallest useful implementation, keep tests green, and consolidate redundant tests. Use surrounding style. Each code file starts with two `ABOUTME: ` lines (100 characters or fewer per line).
6. **Verify incrementally.** During development, run focused relevant tests and checks; avoid repeatedly running the full suite after every edit. For retrospective tests covering existing code, demonstrate effectiveness with a representative deliberately introduced defect, then restore the code, as specified in `gotchas.md`.
7. **Update affected documentation in the same PR.** Consult the targeted audit below. Documentation stays with the behavior it describes, not in a deferred docs-only PR.
8. **Run completion gates once the change is ready.** All required checks must pass before reporting a card complete:
   ```bash
   uv run ruff format src tests
   uv run ruff check src tests
   uv run mypy                       # strict
   uv run pytest tests/unit tests/component --cov --cov-fail-under=80 -q
   uv run pytest tests/e2e tests/integration -m "not needs_network and not live and not live_openai and not live_lmstudio" -q
   uv run pre-commit run --all-files
   ```
   The offline e2e/integration command also runs in CI. Tests marked `needs_network` or `live` run in `network.yml` and `live.yml`; when a card changes those paths, dispatch the relevant workflow from Actions on the branch and use the run as evidence. If a check cannot run, state that explicitly; never claim it passed. Fix failing hooks rather than bypassing them (`--no-verify`, `--no-hooks`, etc.).
9. **Review the diff proportionately.** Check acceptance criteria, correctness, security and fact provenance, test duplication, accidental scope, and docs. An independent reviewer is expected for high-risk or unusually complex work; otherwise a concise self-review is sufficient. Correct actual findings without expanding into unrelated work.
10. **Commit, push, and open the PR.** Use an imperative commit message, without attribution lines or em dashes. PR title: `<card-id>: <title>`; begin the body with `Closes #<issue>`, then summarize behavior, checks, relevant docs, limitations, any split, and file count.
11. **Report and wait for approval.** Send a short summary of changes, checks actually passed, important remaining risks, and any decision needed. Post the same summary on the issue (`gh issue comment <n>`). Merge only after Joe P approves; do not auto-merge or poll CI repeatedly. After merging, verify the issue closed and update `main`. Start another card only when asked, and tell Joe P to start it in a fresh session; do not continue in this one.

## Targeted documentation audit
Check documents *affected by the change*, not a mandatory full-repository sweep:
- `README.md`: user-visible behavior, Status and "Try what exists" when affected.
- `docs/README.md`: index, configuration listing, or decision table when affected.
- `docs/codebase.md`: layout, flow, or extension guidance when architecture changes.
- `docs/contributing.md` or this guide: setup, workflow, or verification changes.
- The card's owning documentation and commands altered by the change. Run new or changed commands and critical existing commands when a change could break them.
- `docs/adr/`: significant design decisions, not routine implementation choices.
- `NOTICE`: newly included third-party fixtures or materials, with source/license and any required takedown contact.
- `gotchas.md`: update an existing lesson when possible; add a new one only for a genuinely new, generalizable failure mode.

Documentation and its relevant runnable instructions must remain accurate. Avoid unrelated rewrites or repeating all commands on every card.

## Practical reminders
- Never describe disabled, skipped, or stubbed functionality as working. Keep application paths free of mock modes, fake providers, and stubbed HTTP. Recorded real outputs and hostile handwritten inputs can be used as test inputs.
- Treat postings, PDFs, feeds, and model output as untrusted data. The model has no tools or side effects; validators enforce fact provenance.
- Keep one source of truth and avoid unrelated changes. Use evergreen names and retain accurate comments.
- No em dashes in code, comments, docs, commits, or PR text.
- Do not mention specific employers or industries in the repo or fact bank; public evaluation fixtures are exempt when properly attributed in `NOTICE`.
- Ports: API 5309; Vite 5150; infrastructure defaults otherwise.
- Windows: harmless CRLF warnings may appear. Keep generated scratch files in a short path such as `C:/Temp/ccb`, and use an editor tool for files with backslash escapes rather than shell heredocs.

## Where things are
| What | Where |
| --- | --- |
| Binding rules | [CLAUDE.md](../CLAUDE.md) |
| Recorded lessons | [gotchas.md](../gotchas.md) |
| Code layout and extension | [codebase.md](codebase.md) |
| Setup and contribution details | [contributing.md](contributing.md) |
| Design decisions | [adr/](adr/) |
| Data model, pipeline, validators | [data-model.md](data-model.md), [pipeline.md](pipeline.md), [validators.md](validators.md) |
| Providers, errors, retries | [providers.md](providers.md) |
