# Contributing

The binding rules live in [CLAUDE.md](../CLAUDE.md). This page is the short, plain language version. If the two ever disagree, CLAUDE.md wins.

## Workflow
- One card (issue) per branch, one pull request per card, merged to main after review. No worktrees.
- Work in phases of at most five files. Run verification after each phase and wait for approval before the next.
- Test first (TDD): write a failing test, watch it fail, write the minimum code to pass, then refactor.
- Git hooks are never bypassed. If a hook fails, fix the cause.
- Commit messages and PR text carry no attribution lines.

## Code
- Every code file starts with two comment lines, each beginning with `ABOUTME: `.
- Keep it simple and match the surrounding style. Names are evergreen: no "new", "improved" or "enhanced".
- No mocks or fake providers. An unreachable backend fails the test loudly, it is never skipped.

## Tests
Four tiers exist: unit, component, integration and e2e. Markers `live` (needs a real model backend) and `needs_network` (needs the internet) select tests.

## Setup
```bash
uv sync
uv run pytest
```

## Quality gates
Install the hooks once per clone:

```bash
uv run pre-commit install
```

On every commit the hooks run, and CI (`.github/workflows/deterministic.yml`) runs the same checks on every push and pull request:

- **detect-secrets**: blocks committed secrets (baseline in `.secrets.baseline`).
- **ruff lint** and **ruff format check**: style and common errors.
- **mypy --strict**: strict type check over `src` and `tests`.
- **pytest** over the unit and component tiers with `--cov-fail-under=80`. Only `src/cypress_creek` counts toward coverage.

Warnings are errors, and a skipped test fails the whole run, so a missing service can never hide as a skip. Tool versions are pinned by `uv.lock`. Run everything by hand with `uv run pre-commit run --all-files`. Never use `--no-verify`.

