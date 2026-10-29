# Picking up a card (handoff guide)

Written so a new contributor, human or AI assistant, can take a card from the issue board and deliver it the way this repo expects, without asking. Read [CLAUDE.md](../CLAUDE.md) (binding rules) and [gotchas.md](../gotchas.md) (past mistakes turned into rules) first. [codebase.md](codebase.md) explains the code.

## Who and what
- The owner is Joe P (Palicke, JP). We work as coworkers: push back with evidence, ask when blocked.
- The product tailors a job application to a posting without inventing any claim. Nothing the tool outputs may assert a claim that is not backed by a verified fact ID. Deterministic validators enforce this, never prompting. No auto apply, ever.
- The design is the spec (linked from the issue board). A card is a GitHub issue, labeled by lane (`lane:B` and so on). Closed cards are done, so the board is the status. Do not rely on a status list copied elsewhere.

## One time setup
```bash
uv sync                          # Python 3.13 and pinned dependencies
uv run pre-commit install        # git hooks
git config user.name             # must be: jpalicke
git config user.email            # must be: 13882087+jpalicke@users.noreply.github.com
```
Never commit with a personal email address. Secrets live in the environment or a gitignored `.env`.

## The card routine, in order
1. **Read the card.** Pick one from the board ([lanes.md](lanes.md) shows which lanes can run in parallel and how to list ready cards). Scope, out of scope, suggested files, first failing test, test plan, docs owned, depends on. Check the dependencies are closed.
2. **Size it.** A PR aims for at most 10 changed files, hard cap 20 (a bundled third party data file counts as one). If the card will exceed about 10, propose a split before starting. Retitle the issue (for example `B6a`), file the follow up (`B6b`) and say so in the PR. Each piece ships its own docs.
3. **Branch.** `git checkout -b <card-id>-<short-name>` from an up to date `main`. One branch per card. No worktrees.
4. **Test first, always.** Write the failing test, run it, see it fail for the right reason, and only then write implementation. The same goes for every later design change within the card: change the tests first, watch them fail, then change the code. Never write implementation ahead of the test that demands it, and never "fix the tests afterwards". Every tier that applies exists: unit, component, integration, e2e. No tier is ever marked not applicable.
5. **Implement the minimum**, then refactor with the tests green. Match the surrounding style. Every code file starts with two `ABOUTME: ` comment lines (100 characters or fewer per line).
6. **Docs, in the same PR** (see the audit below). Docs never go in a later PR.
7. **Gates.** All must pass with pristine output before you call it done:
   ```bash
   uv run ruff format src tests
   uv run ruff check src tests
   uv run mypy                       # strict
   uv run pytest tests/unit tests/component --cov --cov-fail-under=80 -q
   uv run pre-commit run --all-files
   ```
   If a hook fails: read the whole output, name the tool and cause, fix the root cause, re-run. Never use `--no-verify` or any bypass flag.
8. **Commit and push.** Short imperative message, no attribution lines, no em dashes. The hooks run on commit.
9. **Open the PR.** Title `<card-id>: <title>`, body starts with `Closes #<issue>` (that closes the card when it merges), then what changed, the split if any, the docs updated, and the file count. No attribution lines.
10. **Report.** Send Joe P a short summary: what was done, the gates that passed, a perfectionist view and a pragmatist view of the work, and what you are waiting for. Post the same summary as a comment on the card's issue (`gh issue comment <n>`).
11. **Wait.** Merge only when Joe P says to. Never enable auto merge. Do not poll CI. When he says "merge", merge the PR, confirm the issue closed, update `main`, and start the next card only when asked.

## Documentation audit (run before reporting)
Stale docs are the most common failure here. For every new module, config file, command, rule and decision, grep these and update each place that should mention it:
- The doc the card owns (named in the card), including any copy and paste command. Run each command and check the output.
- `README.md`: the Status line, the "Try what exists" table, and any user facing wording the card calls for.
- `docs/README.md`: the doc index, the decision record table, the configuration list.
- `docs/codebase.md`: the layout tree, the flow diagram, "Ideas to know", and "Adding a new thing, by example".
- `docs/contributing.md` and this file, if a process rule or setup step changed.
- An ADR in `docs/adr/` for any design decision, with the next free number.
- `NOTICE` if third party material is added. Third party data or fixtures need their source and license listed.
- `gotchas.md` after any correction from Joe P: add the pattern as a strict rule with the reason.

## Rules people trip over
- Never say a claim is "working" when functionality is disabled, skipped or stubbed. No mocks, fake providers or stubbed HTTP in any call path. Recorded real outputs and hostile hand written outputs may be inputs.
- All external input is hostile: postings, PDFs, feeds, model output. The model has no tools and no side effects, and its output is data until a validator passes it.
- One source of truth. Never fix a display problem by copying state.
- Names are evergreen (never "new", "improved", "enhanced"). Do not remove comments unless provably false. Comments describe the code as it is, not its history.
- Do not make changes unrelated to the card. File an issue instead.
- No em dashes anywhere (code, comments, docs, commits, PRs, chat).
- Do not mention any specific employer or industry in the repo.
- Ports: API 5309, Vite dev server 5150. Infrastructure keeps its defaults.
- Windows notes: git prints harmless CRLF warnings. Keep generated scratch files in a short directory such as `C:/Temp/ccb`, and write files containing backslash escapes with an editor tool, not a shell heredoc.

## Where things are
| What | Where |
| --- | --- |
| Binding rules | [CLAUDE.md](../CLAUDE.md) |
| Past mistakes as rules | [gotchas.md](../gotchas.md) |
| Code layout, flow, how to extend | [codebase.md](codebase.md) |
| Setup, gates, audit, ABOUTME headers | [contributing.md](contributing.md) |
| Why decisions were made | [adr/](adr/) |
| Data model, pipeline, validators | [data-model.md](data-model.md), [pipeline.md](pipeline.md), [validators.md](validators.md) |
| Providers, errors, retry | [providers.md](providers.md) |
