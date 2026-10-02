# Cypress Creek Job Board

Tailors a job application to a posting without ever stating a claim the author has not verified.

It reads a posting, extracts requirements, maps each requirement to facts in a curated bank, reports gaps honestly, and only then helps draft. Every claim cites verified fact IDs, enforced by deterministic validators rather than prompting. There is no auto apply, and a human reviews every draft.

Status: early implementation. The fact bank, the posting normalizer, the tag alias table and the deterministic support gate exist as libraries. There is no app to start yet. Work is tracked as a kanban in this repo's issues (one issue per card, labeled by lane). Cards marked `core` are the smallest set that makes the repo credible and demoable on its own.

License: MIT.

## Quick start (developers)

```bash
uv sync                          # install pinned dependencies (Python 3.13)
uv run pre-commit install        # install the git hooks once per clone
uv run pytest                    # run all tests
uv run pre-commit run --all-files  # run every quality gate by hand
```

What is runnable today: the test suite, the quality gates and a few library pieces you can try from the command line (below). There is no app to start yet. This section grows with each card.

## Try what exists
Each command is copy and paste, and lives with its documentation:

| Piece | Where the command is |
| --- | --- |
| Validate your fact bank | [docs/data-model.md](docs/data-model.md#try-it-locally) |
| Look up a tag alias | [docs/data-model.md](docs/data-model.md#try-the-alias-table) |
| Normalize posting text | [docs/pipeline.md](docs/pipeline.md#stage-0-normalize-the-posting) |
| Run the support gate on a requirement | [docs/pipeline.md](docs/pipeline.md#try-it-locally) |

## Documentation
New here? Read [docs/codebase.md](docs/codebase.md) first. [docs/README.md](docs/README.md) is the index: the data model, the pipeline stages, the decision records and how we work.

See [docs/contributing.md](docs/contributing.md) for how we work.
