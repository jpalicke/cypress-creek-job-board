# Contributing

The binding rules live in [CLAUDE.md](../CLAUDE.md). This page is the short, plain language version. If the two ever disagree, CLAUDE.md wins.

## Workflow
- One card (issue) per branch, one pull request per card, merged to main after review. No worktrees.
- Work in phases of at most five files. Run verification after each phase and wait for approval before the next.
- Test first (TDD): write a failing test, watch it fail, write the minimum code to pass, then refactor.
- Git hooks are never bypassed. If a hook fails, fix the cause.
- Commit messages and PR text carry no attribution lines.
- Documentation ships in the same PR as the implementation, always. Splitting docs into a later PR needs Joe P's explicit approval.

## Code
- Every code file starts with two comment lines, each beginning with `ABOUTME: `.
- Keep it simple and match the surrounding style. Names are evergreen: no "new", "improved" or "enhanced".
- No mocks or fake providers. An unreachable backend fails the test loudly, it is never skipped.

## Tests
Four tiers exist: unit, component, integration and e2e. Markers `live` (needs a real model backend) and `needs_network` (needs the internet) select tests. Property tests use Hypothesis, and they run with the rest of the suite.

## Documentation checklist
Before a PR is ready, in the same PR:
- The doc the card owns is updated, and any copy and paste command in it was run.
- README.md status and "Try what exists" reflect what now works.
- The docs index (docs/README.md) lists any new doc or decision record.
- docs/codebase.md matches the code: layout, the flow diagram and the module list.
- A new design decision has an ADR in `docs/adr/`.
- Configuration files (for example `config/aliases.yaml`) are described in the doc that owns them.

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
- **ABOUTME header check**: every code file starts with the two line header (see below).
- **mypy --strict**: strict type check over `src`, `tests` and `scripts`.
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

## ABOUTME headers
Every code file starts with two comment lines, each beginning with `ABOUTME: `. The first says what the file does, the second adds detail. A shebang line may come first in scripts. The check (`scripts/check_aboutme.py`) verifies structure only. It skips Markdown, JSON, YAML, lockfiles and other non-code files.

```python
# ABOUTME: Parses a posting into requirements.
# ABOUTME: Rejects text that fails size checks.
```

TypeScript and JavaScript use `// `, shell uses `# `, SQL uses `-- `, and Svelte puts each line in its own HTML comment on the first two lines:

```svelte
<!-- ABOUTME: Shows the gap report. -->
<!-- ABOUTME: Renders all text as plain text. -->
```

