# Documentation

Start with the [README](../README.md) for setup and the commands you can run today.

| Doc | What it covers |
| --- | --- |
| [codebase.md](codebase.md) | Start here if you are new: layout, how the pieces fit, ideas to know, how a card goes |
| [data-model.md](data-model.md) | The fact bank, Posting and Requirement, and the tag alias table (`config/aliases.yaml`) the company name key (`company_key`), the SQLite storage and migrations, and the discovery tables (watchlist, denied companies, blacklist and its filter) |
| [pipeline.md](pipeline.md) | HTML posting text extraction, posting normalization, the prompt builder (extraction, entailment and draft prompts), draft help, accepting extraction output, stage 1 extraction, stage 2 retrieval, stage 3 entailment, stages 4 and 5 score and report, running the pipeline with an optional trace and a derived run id, the support gate, the score |
| [evals.md](evals.md) | Eval CLI dry runs and real Ollama smoke runs, whole-run budgets, typed records and traces, SQLite resume, scratch JSONL audit exports, fictional sample fact bank and planted gaps, real posting fixtures with hand labels and the label check |
| [e3-label-decisions.md](e3-label-decisions.md) | Why each hand label is what it is, the judgment calls for Joe P to review, and the closed postings and their replacements |
| [validators.md](validators.md) | The grounding validators V1 to V14: what each rejects and its known limits |
| [providers.md](providers.md) | The provider interface, typed errors, retry policy, backend config, the loopback rule, the Ollama adapter and the budget guard |
| [setup.md](setup.md) | Fetch one public posting link, inspect raw bytes and provenance, and understand network behavior and typed failures. Also fetch a job board politely, fetch a Greenhouse, a Lever or an Ashby board, the fetch cache location, the three fetch environment variables and how to clear the cache |
| [architecture.md](architecture.md) | How guarded public HTTP fetching pins the connection, bounds the response and isolates DNS behind a deadline, and how the polite fetch layer (rate limiter, refresh window, ETag cache, backoff) sits on top of it, and the board adapter interface (listings, probe, typed errors, the Greenhouse, Lever and Ashby mappings, Lever paging and region discovery, Ashby unlisted jobs and its shape-only probe, the shared feed helpers and the failure modes) |
| [threat-model.md](threat-model.md) | The hostile HTML and hidden-content boundary, prompt structure (T1 to T4), URL target validation and guarded HTTP transport, SSRF rules, compatibility limits and test coverage |
| [README, discovery findings](../README.md#discovery-findings-and-sources) | The ATS findings table with links to each provider's docs, the politeness policy, and the not legal advice statement |
| [spec.md](spec.md) | The full design spec: goals, architecture, data model, pipeline, providers, validators, evals, threat model, discovery, ingestion, UI, testing and the card plan |
| [lanes.md](lanes.md) | How the lanes depend on each other and which can be worked in parallel |
| [handoff.md](handoff.md) | The card routine step by step, for a new contributor or assistant picking up a card |
| [contributing.md](contributing.md) | How we work, quality gates, dependency audit, ABOUTME headers, docs checklist |
| [E2b2 documentation audit](audits/AUDIT_REPORT_2026-10-17.md) | Verified runner and export claims against the implementation |

## Decision records
| ADR | Decision |
| --- | --- |
| [0001](adr/0001-fact-bank-enums-and-defaults.md) | Fact bank enums, defaults and the bank location |
| [0002](adr/0002-posting-whitespace-and-normalization-order.md) | Posting whitespace rules and normalization order |
| [0003](adr/0003-score-formula-and-downgrade-only.md) | Score formula, what supported means, downgrade only |
| [0004](adr/0004-company-key-rules.md) | Company key rules, Unicode confusables data, spaces removed |
| [0005](adr/0005-sqlite-and-migrations.md) | SQLite for mutable state, numbered SQL migrations, data directory |
| [0006](adr/0006-issuer-field-and-issuer-matching.md) | Optional issuer on facts and requirements, matched with company_key |
| [0007](adr/0007-provider-config-toml-and-loopback.md) | Provider config as TOML plus environment overrides, remote hosts are opt in |
| [0008](adr/0008-ollama-truncation-signature-and-window-floor.md) | How the Ollama adapter detects silent truncation, and the 2048 window floor |
| [0009](adr/0009-url-target-validation.md) | Public URL targets, strict hostname syntax and validation of every resolved address |
| [0010](adr/0010-extraction-stage-design.md) | How stage 1 extraction trusts the model: code sets spans and importance, failures are incomplete |
| [0011](adr/0011-entailment-can-only-lower-support.md) | How stage 3 entailment can change support: the lower of ceiling and verdict, citations required, rationale display only |
| [0012](adr/0012-report-fails-closed-and-cites.md) | How the gap report is built: fails closed, incomplete when a stage failed, every claim cites or the report is refused |
| [0013](adr/0013-pinned-http-transport.md) | Pinned HTTP connections, deadline isolation and bounded response decoding |
| [0014](adr/0014-run-id-is-derived-from-the-inputs.md) | The run id is a hash of the posting, the fact bank, the backend and the model |
| [0015](adr/0015-link-fetch-browser-signals.md) | Only clear HTTP authentication signals need browser guidance during raw link fetching |
| [0016](adr/0016-html-text-parsing.md) | Bounded standard-library HTML parsing and best-effort visible text rules |
| [0017](adr/0017-tombstones-are-removed-only-by-a-human-call.md) | Denied companies are tombstoned by key and board, and only an explicit call lifts one |
| [0018](adr/0018-eval-run-identity.md) | Eval resume identity includes every audited input, stays distinct from the pipeline run id, and uses SQLite for live runs with JSONL exports |
| [0019](adr/0019-polite-fetch-timing-and-clocks.md) | Polite fetch delay counts from the end of the previous request, wall time stamps the cache and monotonic time drives the limiter, and the transport passes 304, 429 and 5xx through only on request |
| [0020](adr/0020-adapter-failure-modes.md) | Adapter failure modes: a feed shape violation skips the whole board by name, only a 404 means a missing board, other refusals propagate, and description HTML is unescaped exactly once |
| [0021](adr/0021-per-job-skipping.md) | Per job skipping: a malformed job is skipped and reported in `BoardFetch.skipped`, and a board that skips more than 10 percent of its jobs still fails whole |
| [0022](adr/0022-lever-pagination-and-region.md) | Lever paging and region: pages end on a short page, a board still full at 50 pages fails whole instead of truncating, a repeated posting keeps its first copy, the host is found by asking US then EU and remembered in memory only, and the feed has no company name |
| [0023](adr/0023-ashby-unlisted-jobs-probe-shape-and-weak-etag.md) | Ashby: an unlisted job is dropped and counted in `BoardFetch.unlisted` instead of skipped, the skip budget covers listed jobs only, `probe` checks the shape of the board and not each job, and the weak ETag is sent back unchanged and answered with a 304 |
| [0024](adr/0024-hand-labels-are-written-before-runs-and-carry-provenance.md) | Hand labels are written before any run from the posting and bank alone, carry provenance and a pending review, follow the human reading of importance, and are validated against the posting, the bank and the planted gaps |
| [0026](adr/0026-draft-help-checks-each-sentence.md) | Draft help: every sentence checked alone, failures shown as not verified, a gap gets no model call, nothing can be sent |

## Configuration
- `config/aliases.yaml`: tag alias table, described in [data-model.md](data-model.md#tag-alias-table).
- `config/weights.yaml`: score weights and support values, described in [pipeline.md](pipeline.md#score).
- `config/confusables.txt`: Unicode confusables data (do not hand edit), used for company names and described in [data-model.md](data-model.md#company-names-company_key).
- `CYPRESS_CREEK_DATA_DIR` (default `data/`, gitignored): where the SQLite database lives, described in [data-model.md](data-model.md#storage-sqlite-and-migrations).
- Eval `--out` selects that SQLite database, while optional `--export` writes a JSONL audit snapshot only under `evals/scratch/`; see [evals.md](evals.md#run-the-harness).
- `config/provider.toml` (or the file named by `CYPRESS_CREEK_CONFIG`) and `CYPRESS_CREEK_<FIELD>` variables: which model backend to use and the run budget limits, described in [providers.md](providers.md#configuration). API keys are read only from the environment variable the file names.
- `CYPRESS_CREEK_FETCH_REFRESH_SECONDS` (default `900`), `CYPRESS_CREEK_FETCH_HOST_DELAY_SECONDS` (default `1.0`) and `CYPRESS_CREEK_FETCH_MAX_RETRIES` (default `4`, at most `8`): the polite fetch policy, described in [setup.md](setup.md#polite-fetch-settings-and-cache). The fetch cache lives in `fetch_cache` under `CYPRESS_CREEK_DATA_DIR`.
- `facts.private/bank.yaml` (gitignored) or the path in `CYPRESS_CREEK_BANK`: your fact bank.

URL target validation and guarded HTTP fetching have no configuration or environment override for private destinations. In particular, the provider's `allow_remote` setting does not relax the URL guard's public-address rule.
