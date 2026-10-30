# Picking up a card (handoff guide)

This is the practical card routine. [CLAUDE.md](../CLAUDE.md) defines binding engineering and safety rules; [gotchas.md](../gotchas.md) records lessons from past mistakes. Read the relevant sections, not every document on every iteration. [codebase.md](codebase.md) explains the code.

## Cards
- The design linked from the issue board is the spec. Cards are GitHub issues with lane labels (`lane:B`, etc.). Closed issues are the source of truth for completion; do not maintain a duplicate status list.

## One-time setup
```bash
uv sync                          # Python 3.13 and pinned dependencies
uv run pre-commit install        # git hooks
git config user.name             # must be: jpalicke
git config user.email            # must be: 13882087+jpalicke@users.noreply.github.com
```

## The card routine
1. **Understand the card.** Check scope, dependencies, acceptance criteria, and relevant design documents. Use [lanes.md](lanes.md) to identify ready cards. Treat a card's suggested first failing test and test plan as guidance, not a mandate to add redundant tests. Identify the behavior and risks the tests need to establish.
2. **Choose a proportional workflow** as [Development approach](../CLAUDE.md#development-approach) describes, including when subagents are allowed.
3. **Size and branch.** Keep the PR within the size bound in [Development approach](../CLAUDE.md#development-approach). Each split delivers its own usable behavior and relevant docs. Start an up-to-date branch: `git checkout -b <card-id>-<short-name>`.
4. **Test meaningful behavior first,** following [TDD and test selection](../CLAUDE.md#tdd-and-test-selection).
5. **Implement, then refactor.** Make the smallest useful implementation, keep tests green, and consolidate redundant tests. Keep each `ABOUTME: ` line to 100 characters or fewer.
6. **Verify incrementally,** following [Verification and review](../CLAUDE.md#verification-and-review). Retrospective tests need the effectiveness check in [TDD and test selection](../CLAUDE.md#tdd-and-test-selection).
7. **Update affected documentation in the same PR** using the targeted audit below.
8. **Run completion gates once the change is ready.** All required checks must pass before reporting a card complete:
   ```bash
   uv run ruff format src tests
   uv run ruff check src tests
   uv run mypy                       # strict
   uv run pytest tests/unit tests/component --cov --cov-fail-under=80 -q
   uv run pytest tests/e2e tests/integration -m "not needs_network and not live and not live_openai and not live_lmstudio" -q
   uv run pre-commit run --all-files
   ```
   The offline e2e/integration command also runs in CI. Tests marked `needs_network` or `live` run in `network.yml` and `live.yml`; when a card changes those paths, dispatch the relevant workflow from Actions on the branch and use the run as evidence.
9. **Review the diff** as [Verification and review](../CLAUDE.md#verification-and-review) describes, also checking acceptance criteria, fact provenance, and docs.
10. **Commit, push, and open the PR.** Use an imperative commit message. PR title: `<card-id>: <title>`; begin the body with `Closes #<issue>`, then summarize behavior, checks, relevant docs, limitations, any split, and file count.
11. **Report and wait for approval.** Report as [Verification and review](../CLAUDE.md#verification-and-review) describes and post the same summary on the issue (`gh issue comment <n>`). Merge only after Joe P approves. After merging, verify the issue closed and update `main`. Start another card only when asked, and tell Joe P to start it in a fresh session; do not continue in this one.

## Targeted documentation audit
Grep these for the names, commands, flags, and paths the change touched, and edit only the matching sections, as [CLAUDE.md](../CLAUDE.md) requires. This is not a full-repository sweep:
- `README.md`: user-visible behavior, Status and "Try what exists" when affected.
- `docs/README.md`: index, configuration listing, or decision table when affected.
- `docs/codebase.md`: layout, flow, or extension guidance when architecture changes.
- `docs/contributing.md` or this guide: setup, workflow, or verification changes.
- The card's owning documentation and commands altered by the change. Run new or changed commands and critical existing commands when a change could break them.
- `docs/adr/`: significant design decisions, not routine implementation choices.
- `NOTICE`: newly included third-party fixtures or materials, with source/license and any required takedown contact.
- `gotchas.md`: update an existing lesson when possible; add a new one only for a genuinely new, generalizable failure mode.

Documentation and its relevant runnable instructions must remain accurate. Avoid unrelated rewrites or repeating all commands on every card.

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
