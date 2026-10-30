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
Four tiers exist: unit, component, integration and e2e. Markers `live` (needs a real model backend), `live_openai`, `live_lmstudio` and `needs_network` (needs the internet) select tests. The `live` tests need a running Ollama with `qwen3.5:0.8b` (see [providers.md](providers.md#try-it-locally)) and are not in the gated unit and component run (`live.yml` runs them weekly and on demand). The Anthropic live test also carries `needs_network` and needs `ANTHROPIC_API_KEY` in your shell; run the Ollama ones, integration and end to end, with `pytest tests/e2e tests/integration -m "live and not needs_network and not live_openai and not live_lmstudio"` (the selector `live.yml` uses) and the Anthropic one with `uv run pytest tests/integration/test_anthropic_live.py -q`. The Anthropic real call was run once with a real key on 2026-10-30 and passed; see [issue #129](https://github.com/jpalicke/cypress-creek-job-board/issues/129). The OpenAI and LM Studio live tests are run by hand or by the manual `openai-live` workflow, see [setup.md](setup.md#run-the-lm-studio-and-openai-live-tests) and [issue #130](https://github.com/jpalicke/cypress-creek-job-board/issues/130). The offline e2e and integration tests run in the `e2e` CI job, and the public-internet ones in `network.yml`. **A test that needs a model backend, a credential or a desktop app carries a backend marker (`live`, `live_openai`, `live_lmstudio`), and every CI selector excludes the backend markers it cannot serve.** Property tests use Hypothesis, and they run with the rest of the suite.

The polite fetch layer has a `needs_network` integration test that fetches a real public job board feed through the real transport, then revalidates a stale cache entry and expects a real 304: `uv run pytest tests/integration/test_polite_client_network.py -q`. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch `discovery/polite_client.py`, `cache.py` or the transport's conditional request handling.

The Greenhouse adapter has a `needs_network` integration test that maps a real large public board to listings through the real polite client, checks that its skipped jobs stay within the skip budget, then probes a real board and a made-up slug: `uv run pytest tests/integration/test_greenhouse_network.py -q`. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch anything under `discovery/adapters/` or the transport's 404 handling.

The Lever adapter has its own `needs_network` integration test: it reads a real large public board across pages (at a page size of 10, about 32 requests, so it takes about a minute and a half), probes it, probes and fetches a made-up slug, and finds a real board that lives only on the EU host: `uv run pytest tests/integration/test_lever_network.py -q`. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch `discovery/adapters/lever.py`, `discovery/adapters/feed_common.py` or the paging.

The Ashby adapter has its own `needs_network` integration test: it fetches a real public board, checks every listing, probes it, probes and fetches a made-up slug, and revalidates the stored weak ETag against the real server, which must answer 304: `uv run pytest tests/integration/test_ashby_network.py -q`. It takes a few seconds. It needs the internet and fails, never skips, when the network is unreachable. Run it when you touch `discovery/adapters/ashby.py`, `discovery/adapters/feed_common.py` or the polite client's conditional requests.

The PDF extractor has its own tests, all offline: `uv run pytest tests/unit/test_pdf_fixtures.py tests/integration/test_pdf_hostile.py tests/component/test_pdf_worker.py tests/e2e/test_pdf_upload_process.py -q --no-cov` (the fixture generator is deterministic, every hostile file gives its listed outcome, the child process limits hold, and the real server survives a bomb). See [evals.md](evals.md#hostile-pdf-fixtures-and-the-hidden-carrier-class).

The posting fixtures and their hand labels have their own check: `uv run python -m evals.harness.check_labels`. Its tests are listed in [evals.md](evals.md#posting-fixtures-and-hand-labels). Run it when you touch anything under `evals/fixtures/` or `evals/harness/labels.py`. A label edit must be committed before any eval run, and the scorer refuses labels that are not.

The scorer (`evals/harness/score.py`, `metrics.py`, `injection.py`) and the injection corpus have unit, component, e2e and live tests; the command is in [evals.md](evals.md#scoring-a-run). Run it when you touch either file or `ReportRow`.

The discovery routes have component tests over loopback boards (`uv run pytest tests/component/test_api_discovery_runs.py -q`), an offline e2e test on the real server (`tests/e2e/test_api_discovery_runs_process.py`), a `needs_network` test over real Lever boards (`tests/integration/test_api_discovery_runs_network.py`) and a `live` test with a real Ollama model (`tests/integration/test_api_discovery_runs_live.py`). The network and live ones run in `network.yml` and `live.yml`.

The API has an e2e test that starts the real server on port 5309: `uv run pytest tests/e2e/test_api_server_process.py -q --no-cov`. Nothing else may be listening on that port, and it fails, never skips, if it is busy. Run it when you touch anything under `src/cypress_creek/api/`.

The integration and e2e tiers are not in the gated run, so run them by hand when you touch what they cover. For the blacklist: `uv run pytest tests/e2e/test_blacklist_process.py tests/integration/test_blacklist_dns.py -q`. The e2e file starts real child Python processes against a real temp SQLite file. The integration file is marked `needs_network` and resolves a real host, so an unreachable network makes it fail, never skip.

Cue coverage in the report has an e2e test (a child Python process renders the text report for a posting with an omitted cue sentence) and a `live` integration test (a real Ollama extraction of the sample posting, checked against V13, the trace and the rendered count): `uv run pytest tests/e2e/test_cue_coverage_process.py tests/integration/test_cue_coverage_live.py -q`. The live test fails, never skips, when Ollama or the model is missing.

## Documentation checklist
Before a PR is ready, in the same PR:
- The doc the card owns is updated, and any copy and paste command in it was run.
- README.md status and "Try what exists" reflect what now works.
- The docs index (docs/README.md) lists any new doc or decision record.
- docs/codebase.md matches the code: layout, the flow diagram and the module list.
- A new design decision has an ADR in `docs/adr/`. Numbers are sequential and gaps are fine. The latest on main is 0039 (E7) and 0036 is H1c. 0037 is H7b (the discovery routes). Numbers reserved by the plan for open work: 0038 G3, 0040 the runner wiring (#140), 0041 H8. Check `ls docs/adr` and the open pull requests before you pick one; the last PR to merge resolves any clash.
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
- **pytest** over the unit and component tiers with `--cov-fail-under=80`. Only `src/cypress_creek` counts toward coverage. The report lists only files below full coverage. The hook skips commits that touch only `docs/` or Markdown files; CI still runs it on every push.

Three more CI pieces cover the tiers the gated run leaves out:

- **e2e job** (same workflow, every push and pull request): `pytest tests/e2e tests/integration -m "not needs_network and not live and not live_openai and not live_lmstudio"`. These are the offline end to end and integration tests: real child processes, real SQLite files and real loopback servers.
- **windows job** (same workflow, every push and pull request, not a required check): on `windows-latest` it runs only the platform sensitive tests, the PDF extractor (`test_pdf_fixtures.py`, `test_pdf_hostile.py`, `test_pdf_worker.py`), link posting, the API postings routes and the PDF upload against the real server. The extractor starts a child process and uses POSIX resource limits where they exist, so Windows is tested, not assumed. Windows behaviour is asserted in the tests, never skipped. To run it by hand in PowerShell: `uv run pytest tests/unit/test_pdf_fixtures.py tests/integration/test_pdf_hostile.py tests/component/test_pdf_worker.py tests/e2e/test_pdf_upload_process.py -q --no-cov`.
- **`network.yml`** (weekly and on demand, not a pull request gate): `pytest tests/integration tests/e2e -m "needs_network and not live and not live_openai"`. These talk to public job boards and public HTTPS, so an outage or a changed board must not block a merge. Start it by hand from the Actions tab (`workflow_dispatch`) on the branch whose network tests you changed, and quote the run in the pull request. The `live` tests (a real Ollama), under both `tests/integration` and `tests/e2e`, run in `live.yml` the same way. `tests/unit/test_ci_selectors.py` fails if a directory holding a `live` test is not selected there or if any other workflow selects `live` tests.

Every workflow declares `permissions: contents: read` at the top, the minimum a checkout needs. A job that needs more must say why in a comment next to the grant.

Warnings are errors, and a skipped test fails the whole run, so a missing service can never hide as a skip. Tool versions are pinned by `uv.lock`. Run everything by hand with `uv run pre-commit run --all-files`. Never use `--no-verify`.

## The web UI gates
`web/` is checked by `npm --prefix web run verify` (ESLint with the `{@html}` ban, `svelte-check` in strict mode, vitest with an 80 percent coverage gate, the production build and `check-dist`). A pre-commit hook runs it when a file under `web/` changes, and the `web` CI job runs it again and then the Playwright tests (`npm run e2e`) against the real API. Install the locked dependencies once with `cd web && npm ci`; a missing `node_modules` fails the hook, it is never skipped. Write the failing test first in the same way as for Python: a vitest component test, or a Playwright test for anything the browser enforces. Do not add an npm dependency without a reason in [ADR 0038](adr/0038-web-ui-stack-and-csp.md): it needs a license on the allow list and a clean `npm audit` at the high level.

## Dependency audit and licenses
`.github/workflows/audit.yml` runs on every pull request and weekly. It runs `pip-audit` on the locked dependencies and checks every installed license against an allow list (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0). Dependabot proposes weekly updates for Python and GitHub Actions.

Run both locally:

```bash
uv export --locked --no-emit-project --no-hashes > requirements-audit.txt
uv run pip-audit -r requirements-audit.txt --no-deps --disable-pip
uv run pip-licenses --format=json > licenses.json
uv run python scripts/check_licenses.py licenses.json
```

The same workflow also runs `npm audit --audit-level=high` and `python scripts/check_licenses.py --npm-lock web/package-lock.json` for the web dependencies. If the audit fails, upgrade the dependency to the fixed version shown. If a license check fails, prefer replacing the dependency (copyleft such as AGPL is not acceptable). If an exception is truly justified, add an entry with a written reason to `license-exceptions.toml`. The exception is a reviewed change in the pull request, and an entry without a reason is rejected.

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

