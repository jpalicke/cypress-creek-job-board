# Cypress Creek Job Board

Tailors a job application to a posting without ever stating a claim the author has not verified.

It reads a posting, extracts requirements, maps each requirement to facts in a curated bank, reports gaps honestly, and only then helps draft. Every claim cites verified fact IDs, enforced by deterministic validators rather than prompting. There is no auto apply, and a human reviews every draft.

The tool never submits, sends or applies anything for you. Draft help only prints text that you copy by hand, with every sentence checked and failures marked. The checks are heuristics that miss some unsupported claims (see [the draft help limits](docs/pipeline.md#draft-help)), so every draft needs your review.

Status: early implementation. The fact bank, the posting normalizer, the tag alias table, the deterministic support gate, the score formula, the company name normalizer, the SQLite migration runner, the grounding validators, the provider interface, the provider config, the Ollama, Anthropic and openai_compatible (OpenAI and LM Studio) adapters, the budget guard, the prompt builder (extraction, entailment and draft prompts), the extraction stage, candidate retrieval, the entailment stage, draft help for one requirement (every sentence checked, nothing sent), the gap report, the pipeline run, URL target validation, guarded HTTP transport, link fetcher, HTML text extractor, fictional sample fact bank for evals, typed eval run records with SQLite resume and JSONL export, the eval CLI runner, six real posting fixtures with hand labels and their label checker, and the discovery tables with the watchlist, the blacklist table with its deterministic filter, the polite fetch layer (fetch policy, per-host rate limiter, ETag disk cache and polite client) and the ATS adapter interface with the Greenhouse, Lever and Ashby adapters (board listings and board probe) exist. The link fetcher returns bounded raw bytes with provenance and typed errors. HTML text extraction is a separate library step that drops hidden content and reports warnings; PDF text extraction and an app workflow are still to come. There is no app to start yet. Work is tracked as a kanban in this repo's issues (one issue per card, labeled by lane). Cards marked `core` are the smallest set that makes the repo credible and demoable on its own.

The pipeline also exposes an in-memory trace of attempted provider calls and actual validator
verdicts. The eval CLI saves those traces with each completed case in SQLite and keeps failed
attempts in failed terminals. Failed requests count toward the whole run budget; missing usage
stays unknown in the audit and receives a conservative budget reservation on resume.

License: MIT.

## Quick start (developers)

```bash
uv sync                          # install pinned dependencies (Python 3.13)
uv run pre-commit install        # install the git hooks once per clone
uv run pytest                    # run all tests
uv run pre-commit run --all-files  # run every quality gate by hand
```

What is runnable today: the test suite, the quality gates and a few library pieces you can try from the command line (below). There is no app to start yet. This section grows with each card.

The full test suite includes real public DNS lookups, live Ollama tests and a live Anthropic test. For the Ollama tests, start Ollama and pull the model described in [the provider guide](docs/providers.md#try-it-locally). The Anthropic live test needs `ANTHROPIC_API_KEY` set in your shell (see [the Anthropic setup](docs/providers.md#the-anthropic-adapter)) and fails, never skips, without it. Network failures fail those tests; they are never skipped. The OpenAI and LM Studio live tests have their own markers (`live_openai`, `live_lmstudio`) and need a key or the LM Studio app, so a plain `uv run pytest` fails those two files without them; deselect with `-m "not live_openai and not live_lmstudio"` (see [the setup guide](docs/setup.md#run-the-lm-studio-and-openai-live-tests)). Unit, component and process tests can be run without public DNS using the commands in [the URL guard test guide](docs/threat-model.md#tests).

## Try what exists
Each command is copy and paste, and lives with its documentation:

| Piece | Where the command is |
| --- | --- |
| Validate the fictional sample fact bank and run its planted gap checks | [docs/evals.md](docs/evals.md#try-it-locally) |
| Validate the six real posting fixtures and their hand labels, and print the fixture set hash | [docs/evals.md](docs/evals.md#posting-fixtures-and-hand-labels) |
| Read why each hand label is what it is | [docs/e3-label-decisions.md](docs/e3-label-decisions.md) |
| Check SQLite eval resume and JSONL audit export | [docs/evals.md](docs/evals.md#run-record-format) |
| Plan and run the technical eval smoke case against Ollama, with an optional audit export | [docs/evals.md](docs/evals.md#run-the-harness) |
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
| Check a draft bullet sentence by sentence, with no model | [docs/pipeline.md](docs/pipeline.md#try-judging-a-draft) |
| Assemble and print a gap report, with no model | [docs/pipeline.md](docs/pipeline.md#try-the-report) |
| Build an OpenAI or LM Studio request without sending it, and run their live tests | [docs/providers.md](docs/providers.md#try-it-locally) |
| Run a posting through every stage against a local model and inspect its trace | [docs/pipeline.md](docs/pipeline.md#try-a-whole-run-against-a-local-model) |
| Run the support gate on a requirement | [docs/pipeline.md](docs/pipeline.md#try-it-locally) |
| Compute a score from requirement supports | [docs/pipeline.md](docs/pipeline.md#score) |
| Normalize a company name to its comparison key | [docs/data-model.md](docs/data-model.md#try-company_key) |
| Add a company to the watchlist and see a denied one refused | [docs/data-model.md](docs/data-model.md#try-the-discovery-tables) |
| Block a company, board slug or domain and see a lookalike filtered | [docs/data-model.md](docs/data-model.md#try-the-blacklist) |
| Fetch a large public Greenhouse board and print its normalized listings | [docs/setup.md](docs/setup.md#fetch-a-greenhouse-board) |
| Fetch a large public Lever board, page by page, and print its normalized listings | [docs/setup.md](docs/setup.md#fetch-a-lever-board) |
| Fetch a public Ashby board in one request and print its normalized listings | [docs/setup.md](docs/setup.md#fetch-an-ashby-board) |
| Create the local database and apply migrations | [docs/data-model.md](docs/data-model.md#try-the-database) |
| Run a grounding validator on model output | [docs/validators.md](docs/validators.md#try-it-locally) |
| Check which cue sentences extraction missed | [docs/validators.md](docs/validators.md#v13-cue-sentence-coverage) |
| See the provider errors and retry policy, load backend config, run the Ollama or Anthropic adapter, print a projected cost | [docs/providers.md](docs/providers.md#try-it-locally) |
| Validate a URL or fetch a bounded public page | [docs/threat-model.md](docs/threat-model.md#try-it-locally) |
| Fetch one public posting link as bounded raw bytes | [docs/setup.md](docs/setup.md#fetch-a-posting-link) |
| Extract readable text from HTML bytes | [docs/pipeline.md](docs/pipeline.md#html-posting-text) |
| Fetch a public job board feed politely: download, cache hit, then a 304 revalidation | [docs/setup.md](docs/setup.md#fetch-a-job-board-politely) |

## Discovery findings and sources
Discovery reads the public job board feeds of three applicant tracking systems. These are findings from reading each provider's documentation and robots.txt on 2026-10-01, not guarantees. None of this is legal advice. The conclusion drawn here is that the three feeds are public by design and that a small personal tool polling an approved list is low risk. Their documentation is silent on terms and limits in some cases, so polite behavior is the mitigation.

| ATS | Endpoint | Company name in feed | Cache signals | Docs and robots findings (checked 2026-10-01) |
| --- | --- | --- | --- | --- |
| [Greenhouse](https://developers.greenhouse.io/job-board.html) | `boards-api.greenhouse.io/v1/boards/{token}/jobs` (board info gives the org name, `?content=true` adds descriptions) | Yes, `company_name` per job | `ETag` present, `max-age=0, must-revalidate`, gzip. No pagination: one response held all 714 jobs of a large board. | Docs say no auth for any GET. robots.txt disallows only `/embed/`. No published terms or rate limits for the feed. The adapter also reads the board info endpoint (`/v1/boards/{token}`) for the organization name. Verified against a large public board on 2026-10-14: a missing board answers HTTP 404. |
| [Lever](https://github.com/lever/postings-api) | `api.lever.co/v0/postings/{slug}?mode=json&limit=N&skip=M` (EU accounts: `api.eu.lever.co`, and the US host answers 404 for them) | No. Slug is the identity. | `ETag` present. Pagination by `skip` and `limit`: a bare JSON array, and a page past the end is `[]`. A page of 100 postings with descriptions was 1.9 MB. | README says published postings are public. robots.txt allows all with `Crawl-delay: 1`. The 2 per second limit applies to application POSTs only. The adapter asks the US host first, then the EU host, and reports no organization name. Verified against a large public board on 2026-10-14: a missing board answers HTTP 404 with a JSON body on both hosts. |
| [Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api) | `api.ashbyhq.com/posting-api/job-board/{name}` | No. Board name is the identity. | `Cache-Control: public, max-age=60`, weak `ETag` of the form `W/"job-board:..."`, CORS open. No pagination and no limit parameter: one response holds the whole board, and a board of 63 jobs with descriptions was 1.95 MB. | Docs silent on terms and limits. robots.txt for the API host returned 401. Customer ToS has a general no-overburden clause. The adapter asks for no compensation data and reports no organization name. Verified against a large public board on 2026-10-19: a missing board answers HTTP 404 with a plain text body, and the real server answers 304 to `If-None-Match` carrying the weak tag unchanged. Every job says whether it is listed, and the adapter drops the unlisted ones and counts them. |

Workable and SmartRecruiters are candidates for later (documentation read only, not live tested). Recruitee is skipped because its own docs say authentication is required while third party sources disagree.

How the tool behaves, whatever a provider says:
- An honest `User-Agent` (`cypress-creek/<version> (personal job search tool; +<repo URL>)`) and `Accept-Encoding: gzip` on every request.
- At least 1 second between requests to one host, one request at a time. This matches Lever's `Crawl-delay: 1`.
- A board is refreshed at most once per 15 minutes by default (configurable). Ashby's cache lifetime is 60 seconds, so polling faster gains nothing.
- Responses are cached on disk. The stored `ETag` is sent as `If-None-Match`, and a 304 means no change.
- Exponential backoff with jitter on 429 and 5xx, a hard retry cap, and `Retry-After` honored when present.
- List endpoints only. A single job request happens only when the list lacks a description.
- Every request goes through the SSRF guard, and the source URL is kept so a posting can link back to its original.

Settings and the cache location are in [docs/setup.md](docs/setup.md#polite-fetch-settings-and-cache). The design is in [docs/architecture.md](docs/architecture.md#polite-fetching) and [ADR 0019](docs/adr/0019-polite-fetch-timing-and-clocks.md).

## What a report looks like
This is a real run of the "whole run against a local model" command in [docs/pipeline.md](docs/pipeline.md#try-a-whole-run-against-a-local-model): the sample posting, a two fact bank and the `qwen3.5:0.8b` model. The model is small, so its answers vary from run to run, and the report shows exactly what it could and could not back up.

```text
Gap report for P-1: complete
Score: 25.0 out of 100 (triage only, not a probability). Supported 1 of 2. 3 cue sentences not assessed; the score does not cover them.
[none] R-1 (required): You must have 3 years of Python experience.
[partial] R-2 (required): Experience with PostgreSQL is required.
    facts: F-0002
    why: rationale withheld: failed grounding check
Gaps: R-1, R-2
Cue sentence not assessed at offset 224: You must be comfortable working in a small team.
Cue sentence not assessed at offset 287: Kubernetes experience is preferred.
Cue sentence not assessed at offset 323: A degree in computer science is a plus.
```

Every supported row cites a verified fact. A model rationale that fails the grounding checks is withheld rather than shown. The report is also available as JSON (`report.model_dump_json()`), with the backend, model, prompt hashes, usage and a run id derived from the inputs.
The cue warning identifies posting sentences that extraction omitted. Those sentences do not enter the displayed score, so read the warning before using the number for triage.

## What the score means
The score (0 to 100) ranks postings so you can triage them. It is a weighted share of requirements your verified facts support. It is not a probability of getting the job, and a posting with no extractable requirements gets no score at all.

## Documentation
New here? Read [docs/codebase.md](docs/codebase.md) first. [docs/README.md](docs/README.md) is the index: the data model, the pipeline stages, the decision records and how we work.

See [docs/contributing.md](docs/contributing.md) for how we work, and [docs/handoff.md](docs/handoff.md) if you are picking up a card.
