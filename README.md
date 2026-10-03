# Cypress Creek Job Board

Tailors a job application to a posting without ever stating a claim the author has not verified.

It reads a posting, extracts requirements, maps each requirement to facts in a curated bank, reports gaps honestly, and only then helps draft. Every claim cites verified fact IDs, enforced by deterministic validators rather than prompting. There is no auto apply, and a human reviews every draft.

Status: early implementation. The fact bank, the posting normalizer, the tag alias table, the deterministic support gate, the score formula, the company name normalizer, the SQLite migration runner, the grounding validators, the provider interface, the provider config, the Ollama adapter, the budget guard, the prompt builder (extraction and entailment prompts), the extraction stage, candidate retrieval, the entailment stage, the gap report, the pipeline run, URL target validation, guarded HTTP transport, the link fetcher, the fictional sample fact bank for evals and the discovery tables with the watchlist exist as libraries. The link fetcher returns bounded raw bytes with provenance and typed errors; HTML and PDF text extraction and an app workflow are still to come. There is no app to start yet. Work is tracked as a kanban in this repo's issues (one issue per card, labeled by lane). Cards marked `core` are the smallest set that makes the repo credible and demoable on its own.

License: MIT.

## Quick start (developers)

```bash
uv sync                          # install pinned dependencies (Python 3.13)
uv run pre-commit install        # install the git hooks once per clone
uv run pytest                    # run all tests
uv run pre-commit run --all-files  # run every quality gate by hand
```

What is runnable today: the test suite, the quality gates and a few library pieces you can try from the command line (below). There is no app to start yet. This section grows with each card.

The full test suite includes real public DNS lookups and live Ollama tests. For the latter, start Ollama and pull the model described in [the provider guide](docs/providers.md#try-it-locally). Network failures fail those tests; they are never skipped. Unit, component and process tests can be run without public DNS using the commands in [the URL guard test guide](docs/threat-model.md#tests).

## Try what exists
Each command is copy and paste, and lives with its documentation:

| Piece | Where the command is |
| --- | --- |
| Validate the fictional sample fact bank and run its planted gap checks | [docs/evals.md](docs/evals.md#try-it-locally) |
| Validate your fact bank | [docs/data-model.md](docs/data-model.md#try-it-locally) |
| Look up a tag alias | [docs/data-model.md](docs/data-model.md#try-the-alias-table) |
| Normalize posting text | [docs/pipeline.md](docs/pipeline.md#stage-0-normalize-the-posting) |
| Build an extraction prompt with a random boundary | [docs/pipeline.md](docs/pipeline.md#try-the-prompt-builder) |
| Build an entailment prompt that shows only verified facts | [docs/pipeline.md](docs/pipeline.md#try-the-entailment-prompt) |
| Accept proposed requirements from a recorded model output | [docs/pipeline.md](docs/pipeline.md#try-the-accept-step) |
| Extract requirements from a posting with a local model | [docs/pipeline.md](docs/pipeline.md#try-extraction-against-a-local-model) |
| Find candidate facts for requirements, with no model | [docs/pipeline.md](docs/pipeline.md#try-retrieval) |
| Judge a model's entailment answer, with no model | [docs/pipeline.md](docs/pipeline.md#try-judging-an-answer) |
| Ask a local model whether facts support a requirement | [docs/pipeline.md](docs/pipeline.md#try-entailment-against-a-local-model) |
| Assemble and print a gap report, with no model | [docs/pipeline.md](docs/pipeline.md#try-the-report) |
| Run a posting through every stage against a local model and print the gap report | [docs/pipeline.md](docs/pipeline.md#try-a-whole-run-against-a-local-model) |
| Run the support gate on a requirement | [docs/pipeline.md](docs/pipeline.md#try-it-locally) |
| Compute a score from requirement supports | [docs/pipeline.md](docs/pipeline.md#score) |
| Normalize a company name to its comparison key | [docs/data-model.md](docs/data-model.md#try-company_key) |
| Add a company to the watchlist and see a denied one refused | [docs/data-model.md](docs/data-model.md#try-the-discovery-tables) |
| Create the local database and apply migrations | [docs/data-model.md](docs/data-model.md#try-the-database) |
| Run a grounding validator on model output | [docs/validators.md](docs/validators.md#try-it-locally) |
| See the provider errors and retry policy, load backend config, run the Ollama adapter, print a projected cost | [docs/providers.md](docs/providers.md#try-it-locally) |
| Validate a URL or fetch a bounded public page | [docs/threat-model.md](docs/threat-model.md#try-it-locally) |
| Fetch one public posting link as bounded raw bytes | [docs/setup.md](docs/setup.md#fetch-a-posting-link) |

## What a report looks like
This is a real run of the "whole run against a local model" command in [docs/pipeline.md](docs/pipeline.md#try-a-whole-run-against-a-local-model): the sample posting, a two fact bank and the `qwen3.5:0.8b` model. The model is small, so its answers vary from run to run, and the report shows exactly what it could and could not back up.

```text
Gap report for P-1: complete
Score: 25.0 out of 100 (triage only, not a probability). Supported 1 of 2.
[none] R-1 (required): You must have 3 years of Python experience.
[partial] R-2 (required): Experience with PostgreSQL is required.
    facts: F-0002
    why: rationale withheld: failed grounding check
Gaps: R-1, R-2
```

Every supported row cites a verified fact. A model rationale that fails the grounding checks is withheld rather than shown. The report is also available as JSON (`report.model_dump_json()`), with the backend, model, prompt hashes, usage and a run id derived from the inputs.

## What the score means
The score (0 to 100) ranks postings so you can triage them. It is a weighted share of requirements your verified facts support. It is not a probability of getting the job, and a posting with no extractable requirements gets no score at all.

## Documentation
New here? Read [docs/codebase.md](docs/codebase.md) first. [docs/README.md](docs/README.md) is the index: the data model, the pipeline stages, the decision records and how we work.

See [docs/contributing.md](docs/contributing.md) for how we work, and [docs/handoff.md](docs/handoff.md) if you are picking up a card.
