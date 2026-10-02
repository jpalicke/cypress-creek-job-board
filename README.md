# Cypress Creek Job Board

Tailors a job application to a posting without ever stating a claim the author has not verified.

It reads a posting, extracts requirements, maps each requirement to facts in a curated bank, reports gaps honestly, and only then helps draft. Every claim cites verified fact IDs, enforced by deterministic validators rather than prompting. There is no auto apply, and a human reviews every draft.

Status: spec phase done, implementation not started. Work is tracked as a kanban in this repo's issues (one issue per card, labeled by lane). Cards marked `core` are the smallest set that makes the repo credible and demoable on its own.

License: MIT.

## Quick start (developers)

```bash
uv sync                          # install pinned dependencies (Python 3.13)
uv run pre-commit install        # install the git hooks once per clone
uv run pytest                    # run all tests
uv run pre-commit run --all-files  # run every quality gate by hand
```

What is runnable today: the test suite and the quality gates. There is no app to start yet. This section grows with each card.

See [docs/contributing.md](docs/contributing.md) for how we work.
