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

## Dependency audit and licenses
`.github/workflows/audit.yml` runs on every pull request and weekly. It runs `pip-audit` on the locked dependencies and checks every installed license against an allow list (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0). Dependabot proposes weekly updates for Python and GitHub Actions.

Run both locally:

```bash
uv export --locked --no-emit-project --no-hashes > requirements-audit.txt
uv run pip-audit -r requirements-audit.txt --no-deps --disable-pip
uv run pip-licenses --format=json > licenses.json
uv run python scripts/check_licenses.py licenses.json
```

If the audit fails, upgrade the dependency to the fixed version shown. If a license check fails, prefer replacing the dependency (copyleft such as AGPL is not acceptable). If an exception is truly justified, add an entry with a written reason to `license-exceptions.toml`. The exception is a reviewed change in the pull request, and an entry without a reason is rejected.

