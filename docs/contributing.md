# Contributing

The binding rules live in [CLAUDE.md](../CLAUDE.md). This page is the short, plain language version. If the two ever disagree, CLAUDE.md wins.

## Workflow
New here or handing a card to someone else? [handoff.md](handoff.md) is the complete step by step routine.

- One card (issue) per branch, one pull request per card, merged to main after review. No worktrees.
- Keep each PR to roughly 20 changed files. Split a card that would go well past that into several PRs, each with its own docs.
- Work in phases of up to about 20 files. Run verification after each phase and wait for approval before the next.
- Test first (TDD): write a failing test, watch it fail, write the minimum code to pass, then refactor. When a design changes mid card, change the tests first and watch them fail before changing the code.
- When asking for a merge, post the same summary as a comment on the card's issue.
- Git hooks are never bypassed. If a hook fails, fix the cause.
- Commit messages and PR text carry no attribution lines.
- Documentation ships in the same PR as the implementation, always. Splitting docs into a later PR needs Joe P's explicit approval.

## Code
- Every code file starts with two comment lines, each beginning with `ABOUTME: `.
- Keep it simple and match the surrounding style. Names are evergreen: no "new", "improved" or "enhanced".
- No mocks or fake providers. An unreachable backend fails the test loudly, it is never skipped.
- Time goes through the `Clock` protocol in `discovery/rate_limiter.py`. Code that waits or ages data takes a `Clock`, production passes `SystemClock`, and tests pass `ManualClock`, which advances only when told to and records each sleep. That is the one allowed time abstraction. It controls time and is not a mocked collaborator, so do not patch `time.sleep` or add another fake.

## Tests
Four tiers exist: unit, component, integration and e2e. Markers `live` (needs a real model backend), `needs_network` (needs the internet), `live_openai` (the real OpenAI API, needs a key) and `live_lmstudio` (a real LM Studio server, local only) select tests. The last two are separate on purpose: the scheduled `live` workflow selects `live` tests and must never need a credential or a desktop app, so a test that does carries its own marker and its own command (see [setup.md](setup.md#run-the-lm-studio-and-openai-live-tests)). The `live` tests need a running Ollama with `qwen3.5:0.8b` (see [providers.md](providers.md#try-it-locally)) and are not in the gated unit and component run. Every CI test selector must exclude the backend markers it cannot serve: a job that runs tests without a model or a credential selects `not live and not live_openai and not live_lmstudio`, so a test that needs LM Studio or a key never runs there and fails by accident. The Anthropic live test also carries `needs_network` and needs `ANTHROPIC_API_KEY` in your shell; run the Ollama ones with `-m "live and not needs_network"` and the Anthropic one with `uv run pytest tests/integration/test_anthropic_live.py -q`. The Anthropic real call has not yet been run with a real key; see [issue #129](https://github.com/jpalicke/cypress-creek-job-board/issues/129), and for OpenAI and LM Studio [issue #130](https://github.com/jpalicke/cypress-creek-job-board/issues/130). Property tests use Hypothesis, and they run with the rest of the suite.

The polite fetch layer has a `needs_network` integration test that fetches a real public job board feed through the real transport, then revalidates a stale cache entry and expects a real 304: `uv run pytest tests/integration/test_polite_client_network.py -q`. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch `discovery/polite_client.py`, `cache.py` or the transport's conditional request handling.

The Greenhouse adapter has a `needs_network` integration test that maps a real large public board to listings through the real polite client, checks that its skipped jobs stay within the skip budget, then probes a real board and a made-up slug: `uv run pytest tests/integration/test_greenhouse_network.py -q`. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch anything under `discovery/adapters/` or the transport's 404 handling.

The Lever adapter has its own `needs_network` integration test: it reads a real large public board across pages (at a page size of 10, about 32 requests, so it takes about a minute and a half), probes it, probes and fetches a made-up slug, and finds a real board that lives only on the EU host: `uv run pytest tests/integration/test_lever_network.py -q`. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch `discovery/adapters/lever.py`, `discovery/adapters/feed_common.py` or the paging.

The Ashby adapter has its own `needs_network` integration test: it fetches a real public board, checks every listing, probes it, probes and fetches a made-up slug, and revalidates the stored weak ETag against the real server, which must answer 304: `uv run pytest tests/integration/test_ashby_network.py -q`. It takes a few seconds. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch `discovery/adapters/ashby.py`, `discovery/adapters/feed_common.py` or the polite client's conditional requests.

The posting fixtures and their hand labels have their own check: `uv run python -m evals.harness.check_labels`. Its tests are listed in [evals.md](evals.md#posting-fixtures-and-hand-labels). Run it when you touch anything under `evals/fixtures/` or `evals/harness/labels.py`. A label edit must be committed before any eval run.

The integration and e2e tiers are not in the gated run, so run them by hand when you touch what they cover. For the blacklist: `uv run pytest tests/e2e/test_blacklist_process.py tests/integration/test_blacklist_dns.py -q`. The e2e file starts real child Python processes against a real temp SQLite file. The integration file is marked `needs_network` and resolves a real host, so an unreachable network makes it fail, never skip.

Cue coverage in the report has an e2e test (a child Python process renders the text report for a posting with an omitted cue sentence) and a `live` integration test (a real Ollama extraction of the sample posting, checked against V13, the trace and the rendered count): `uv run pytest tests/e2e/test_cue_coverage_process.py tests/integration/test_cue_coverage_live.py -q`. The live test fails, never skips, when Ollama or the model is missing.

## Documentation checklist
Before a PR is ready, in the same PR:
- The doc the card owns is updated, and any copy and paste command in it was run.
- README.md status and "Try what exists" reflect what now works.
- The docs index (docs/README.md) lists any new doc or decision record.
- docs/codebase.md matches the code: layout, the flow diagram and the module list.
- A new design decision has an ADR in `docs/adr/`. Numbers are sequential and the latest is 0024, so the next free number is 0025. Check `ls docs/adr` before you pick one.
- Configuration files (for example `config/aliases.yaml`) are described in the doc that owns them.

## Setup
```bash
uv sync
uv run pytest
```

Polite fetching reads three optional environment variables. Unset or blank means the default, and a bad value raises `FetchConfigError` naming the variable. The full table is in [setup.md](setup.md#polite-fetch-settings-and-cache).

| Variable | Default | Meaning |
| --- | --- | --- |
| `CYPRESS_CREEK_FETCH_REFRESH_SECONDS` | `900` | A cached response younger than this is served with no request. |
| `CYPRESS_CREEK_FETCH_HOST_DELAY_SECONDS` | `1.0` | Minimum gap between requests to one host. |
| `CYPRESS_CREEK_FETCH_MAX_RETRIES` | `4` | Retries on 429 and 5xx, a whole number from 0 to 8. |

The response cache is the `fetch_cache` directory under the data directory: `data/fetch_cache/`, or `$CYPRESS_CREEK_DATA_DIR/fetch_cache/` when that variable is set. It is gitignored. Delete it to force a fresh download.

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

