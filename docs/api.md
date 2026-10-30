# The local API

A FastAPI app that serves JSON and the built web bundle to the browser on the same machine. It is a local tool and must never be reachable from other machines or from a hostile web page the user happens to visit (threats T10, T11 and T15 in the [threat model](threat-model.md)). Every route inherits the rules below. The code is in `src/cypress_creek/api/`.

## Rules every route inherits
| Rule | How it is enforced |
| --- | --- |
| Loopback only | `uv run cypress-creek-api` binds to `127.0.0.1` on port 5309. `CYPRESS_CREEK_API_HOST` exists only so a wrong value can be refused: anything but `127.0.0.1` (including `127.0.0.2`, `::1`, `localhost` and `0.0.0.0`) stops the server with exit code 2 before it listens. There is no `allow_remote` setting for the API. |
| Host check | `HostCheckMiddleware` runs before everything else. The request must carry exactly one `Host` header equal to `127.0.0.1:5309` or `localhost:5309`. Any other name, a different port, a missing port, a second Host header or a non ASCII value gets a typed 403 `host_not_allowed`. This blocks DNS rebinding. |
| CSRF token on writes | Every request except `GET`, `HEAD` and `OPTIONS` needs the header `X-CSRF-Token`, exactly once, with the session token. That includes `POST`, `PUT`, `PATCH`, `DELETE` and any unusual method such as `PURGE`. It is compared with `hmac.compare_digest`. A missing, repeated or wrong token gets a typed 403 `csrf_token_invalid`. The check is middleware after the Host check, so it covers every route, mounted sub-apps, unknown paths and static files alike. |
| Hardening headers | Every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a strict `Content-Security-Policy` (below). Every `/api` answer also carries `Cache-Control: no-store`, so the session token is never cached. The static bundle is not marked no-store. |
| No CORS | No CORS middleware exists, so no `Access-Control-*` header is ever sent and a preflight `OPTIONS` is answered 405. Browsers on other origins are denied by default. |
| One error shape | Failures are `{"error": {"code", "message", "details"?}}` with stable codes. Messages are fixed text. They never carry a secret, a stack trace, a submitted value or remote content. |
| Nothing goes outward | There is deliberately no route that submits an application, sends mail or posts anywhere. A unit test lists the route table and fails if any path or operation name suggests it. |
| No docs routes | `/docs`, `/redoc` and `/openapi.json` are off, so the only routes are the ones in the table below. |

## The token flow
The token is created when the server process starts (`secrets.token_urlsafe(32)`) and lives only in memory. The UI reads it once with `GET /api/session`, which sets no cookie, and sends it as `X-CSRF-Token` on every write. The Host check keeps other sites from reaching that route, and the lack of CORS keeps them from reading the answer. Restarting the server makes a new token. The CSRF check is middleware for the whole app, so a route, a mounted sub-app or a method added later is covered without any extra code.

Because the check runs before routing, a write without the token is refused with 403 whatever the path is. With the token, a write to a path that does not exist gets a plain 404, and a write to a path that exists only for reads gets 405.

## Routes
| Route | Answer |
| --- | --- |
| `GET /api/health` | `{"status": "ok", "backends": [{"provider", "model", "reachable"}]}`. `reachable` is `reachable` when the backend address returns any HTTP answer within 2 seconds, `unreachable` when it does not, and `not_checked` for a backend that cannot be probed yet (everything except Ollama). With no backend configured, `backends` is empty. |
| `GET /api/providers` | `{"providers": [{"provider", "model", "local", "strict_schema", "context_tokens", "cost_per_mtok": {"input", "output"}}]}`. Never a key, an environment variable name or a URL. |
| `GET /api/session` | `{"csrf_token": "..."}`. |

| `POST /api/postings` | Adds a posting. Send `Content-Type: application/json` with `{"source": "paste", "text": "..."}` or `{"source": "link", "url": "https://..."}`; the answer (201) has the new `id`, the normalized `text`, its `text_hash`, `warnings` (such as `control_chars_stripped`), `extraction_warnings` (HTML, such as `hidden_elements_removed`), `fetch_warnings` (such as `cross_host_redirect`), `origin_url` and `created_at`. A link goes through the SSRF guard and the polite fetch limits. A raw body with `Content-Type: application/pdf` (or a link that returns a PDF) is checked for size and the `%PDF-` marker, then read by the PDF extractor in a limited child process ([ADR 0043](adr/0043-pdf-text-in-a-limited-child-process.md)): the posting keeps only the visible text, and `extraction_warnings` counts what was dropped (`hidden_white_text`, `hidden_tiny_text`, `hidden_offpage_text`, `hidden_invisible_text`, `annotations_dropped`, `metadata_dropped`, `form_fields_dropped`). A PDF that cannot be read is a typed 4xx and nothing is stored. |
| `GET /api/postings/{id}/estimate` | What the extraction call would use at most under the configured budget: `{"covers": "extraction", "requests", "input_tokens", "output_tokens", "usd"}`. Nothing is sent to the backend. One entailment call per requirement follows an analysis and is not in this number. |
| `POST /api/postings/{id}/analyze` | Body `{"backend": "<configured provider name>", "confirm_hosted": false}`. Runs the pipeline and answers 200 with `{"report_id", "report"}` where `report` is the `GapReport`. The report may be incomplete: with the backend down it is `status: "incomplete"`, has no score and `incomplete_reasons` says `extraction failed: provider_unavailable`. It is never a 500. A hosted backend needs `confirm_hosted: true`. |
| `GET /api/reports/{id}` | A stored report: `{"report_id", "posting_id", "created_at", "report", "validator_verdicts": [{"stage", "subject", "validator", "passed", "reason"}]}`. The verdicts are those of V4, V5 and V9 over the finished report, without any offending text. |
| `GET /api/facts` | The fact bank from the bank file (`CYPRESS_CREEK_BANK`, default `facts.private/bank.yaml`): `{"facts": [...], "unverified_ids": [...]}`. A missing file is `bank_not_found`. |
| `POST /api/facts/validate` | Body `{"yaml": "<bank file text>", "strict": false}`. Always 200: `{"valid", "fact_count", "unverified_ids", "problem"}` where `problem` is `null` or `{"fact_id", "field", "reason"}`. Strict mode also refuses an unverified fact. The YAML is never echoed. |
| `POST /api/facts` | Adds a fact to the bank file (creating it, and its folder, on the first add). Body `{"claim", "kind", "employer", "issuer", "role", "start", "end", "tags": [{"name", "level"}], "evidence": {"type", "pointer"}}` and nothing else: there is no field for an id, a verification date or a share state, so a new fact is always **unverified and local only**, and gets the next id (`F-0001`, ...). Answers 201 with the fact. A rule the fact breaks (a future date, a start after the end, a bad tag level, an over long claim) is a 422 `invalid_request` with the field and the rule in `details`, and nothing is saved. |
| `PUT /api/facts/{id}` | Replaces what a fact says (same body). If anything but the share state changes, the fact becomes **unverified** (its `verified_on` is cleared); saving it unchanged keeps it verified. `not_found` (404) for an unknown id. |
| `PUT /api/facts/{id}/share` | Body `{"share": "shareable" \| "local_only"}`. The only way to change whether a model may see a fact. It keeps the verification. |
| `POST /api/facts/{id}/verify` | Verifies one fact (sets `verified_on` to today). No body, one fact per call, and no bulk route exists. This is the only route that verifies anything. |
| `POST /api/facts/{id}/unverify` | Clears the verification of one fact. |
| `DELETE /api/facts/{id}` | Removes one fact: `{"removed": true}`. Its id is never given to another fact, so an old report that cited it cannot point at a different fact later. |
| `GET /api/watchlist` | `{"entries": [{"company_key", "display_name", "ats", "slug", "identity_evidence", "approved_at", "region"}]}`, ordered by company key. `region` is `us`, `eu` or `null` (Lever only). |
| `POST /api/watchlist` | Adds one approved company. Body `{"display_name", "ats", "slug", "identity_evidence": "strong" \| "weak" \| "none", "approval": "human_confirmed"}` and nothing else. The marker is required, and there is no field for a proposer, so a name a model suggested cannot arrive as if a person had approved it. The server stamps `approved_at`. Answers 201 with the entry. A blacklisted name or board is `blacklisted` (409), a denied one `tombstoned` (409), a repeat `already_watched` (409), and a name or board that cannot be keyed is `invalid_request`. |
| `GET /api/blacklist` | `{"entries": [{"id", "match_kind", "value", "reason", "added_at"}]}`, oldest first. Values are shown normalized: a company key is the folded form (for example `lnltech` for Initech), a slug is trimmed and lower case, and a domain is the bare host. |
| `POST /api/blacklist` | Body `{"match_kind": "company_key" \| "slug" \| "domain", "value", "reason"}`. The value is normalized exactly as the filter does, so `ACME Incorporated` is the same entry as `Acme Corp`. Answers 201 with the entry, `already_blacklisted` (409) for a repeat, `invalid_request` for a value that cannot be normalized. |
| `DELETE /api/blacklist/{id}` | Removes one entry: `{"removed": true}`, or `not_found` (404). Removing it does not add anything to the watchlist. |
| `POST /api/discovery/refresh` | Body `{"backend": "<configured provider name>", "confirm_hosted": false, "cap": 30, "filters": {...}}` (only `backend` is required; `cap` is 0 to 200 and defaults to 30; `filters` are `include_keywords`, `exclude_keywords`, `locations`, `remote`, `exclude_seniority` and `max_age_days`, all optional). Fetches every watched board that is not blacklisted, dedupes and filters, then scores most recent first under the cap, reusing stored scores for free. Answers 200 with the run summary: `{"fetched", "blocked_boards", "filtered_out": {<filter>: count}, "scored", "cache_hits", "unscored", "stopped_by": "cap" \| "budget" \| "backend" \| null, "errors": [{"ats", "slug", "reason"}]}`. A board that fails is listed in `errors` by error type only, and the other boards still run. A blacklisted board is never contacted. With the backend down the run fetches, scores nothing and says `stopped_by: "backend"`. It never answers 500 for a down board or a down backend. The budget is shared by the whole run. A hosted backend needs `confirm_hosted: true`, and a backend name that is not the configured one is `unknown_backend` before anything is fetched. |
| `GET /api/discovery/listings` | The ranked list read back from storage: `{"note", "listings": [{"id", "title", "location", "ats", "slug", "urls", "posted_at", "age_days", "status": "scored" \| "no_score" \| "unscored", "score", "strong", "partial", "none", "incomplete", "run_id"}]}`. Scored rows come first by score then recency, then rows with no score, then unscored rows. `run_id` is the key of the stored gap report. The `note` says the score is for triage and is not a probability. The listing text is not returned. Optional query filters (all repeatable lists except the last three): `include_keyword`, `exclude_keyword`, `location`, `exclude_seniority`, `remote`, `max_age_days`. The list uses the configured backend and the current bank to find stored scores, so a changed bank or model shows rows as unscored until the next refresh. |

| `POST /api/reports/{id}/suggestions` | Draft help for one requirement of a stored report. Body `{"requirement_id": "R-1", "backend": "<the configured backend>", "confirm_hosted": false}` and nothing else (a hosted backend needs `confirm_hosted: true`, as for analysis). A requirement the report found no verified support for is never drafted and makes no model call: `status: "no_support"`. Otherwise `status` is `drafted` (or `not_run` with a `failure` label when the backend is down), `needs_human_review` is always true, `sentences` holds each bullet with its cited `fact_ids`, `passed` (true only if every check passed) and its `verdicts` (`validator`, `passed`, `reason`, never the offending text), and `facts` holds the claim text of each cited fact so a reader sees what the bullet rests on. Unknown report or requirement is `not_found` (404). |

Nothing in the API sends, applies or copies anything: draft help is text for a person to read, tick as reviewed and copy by hand.

### How the routes behave
- **Budget.** Each analysis gets a fresh budget from the provider settings (`max_requests`, `max_usd` and the token limits), checked before every call. A call that would pass it stops with `budget_exceeded` (409) before anything is sent. The budget is per request, not saved across requests.
- **Hosted backends** are never the silent default. The request names the configured backend, a name that is not the configured one is `unknown_backend`, and a backend that is not local needs `confirm_hosted: true` or the answer is `hosted_backend_not_confirmed`.
- **Facts the backend may see.** The pipeline drops `local_only` facts from the prompt for any backend that is not local, the same as everywhere else.
- **Discovery reads only.** The discovery routes make GET requests to the watched boards through the polite fetch layer (per-host delay, ETag cache, retries) and write only to the local database. They send nothing to any board. A Lever board's stored region is told to the Lever adapter before a run, so the first request goes to the right host. The adapters come from `create_app(adapters=...)`; with none given the real Greenhouse, Lever and Ashby adapters are built on the first request, which is the seam the tests use to point boards at loopback servers.
- **No leaks.** No answer contains a key, an environment value, a stack trace or raw remote content. A link that fails says only that it failed and, for a policy block, the stable reason code.

### Body size limits
A request body is limited to 1 MiB, and a PDF upload to `POST /api/postings` (`Content-Type: application/pdf`) to 10 MiB. No other route gets the larger limit, whatever content type it declares. A declared `Content-Length` over the limit is refused with `payload_too_large` (413) before anything is read. Every body is also counted as it is received, so a missing, wrong or chunked length cannot let more through: the request is answered 413 as soon as the count passes the limit. Chunked bodies are accepted within the limit. Pasted text is also capped at 50,000 characters by the normalizer (`posting_too_long`).

### Storage
Postings and reports live in the SQLite database (`CYPRESS_CREEK_DATA_DIR`, default `data/`), created and migrated when the server starts (and, for an app built another way, the first time a route needs it). A posting row holds the normalized text and its provenance; a report row holds the whole `GapReport` as JSON and the validator verdicts, and must point at a stored posting. See [data-model.md](data-model.md#postings-and-reports). The fact bank stays in YAML.

## Error codes
| Code | Status | Meaning |
| --- | --- | --- |
| `host_not_allowed` | 403 | The Host header is not one of the two loopback names on port 5309. |
| `csrf_token_invalid` | 403 | A write came without the session token, or with a wrong one. |
| `not_found` | 404 | No such route or file. |
| `method_not_allowed` | 405 | The path exists but not for this method. This includes CORS preflights. |
| `invalid_request` | 422 | The body or query did not match the route's model. `details` lists each `field` and a `problem`, never the submitted value. |
| `payload_too_large` | 413 | The body is over the size limit. |
| `unsupported_media_type` | 415 | `POST /api/postings` takes JSON or a PDF. |
| `empty_posting` | 422 | The text, or the page text, is empty. Paste the posting text. |
| `posting_too_long` | 413 | The text is over 50,000 characters. |
| `blocked_by_policy` | 422 | The link or a redirect failed the SSRF policy. `details` holds the reason code, and nothing was contacted for a private address. |
| `fetch_failed` | 502 | The link could not be fetched. |
| `needs_browser` | 422 | The page asked for a sign in. |
| `unsupported_content` | 422 | The link returned a type that is not HTML, plain text or PDF. |
| `content_too_large` | 413 | The page is over the fetch limits. |
| `unreadable_content` | 422 | The HTML could not be read as text. |
| `invalid_pdf` | 422 | A PDF upload without the `%PDF-` marker. |
| `pdf_too_large` | 413 | The PDF is over the extractor's size limit. |
| `pdf_too_many_pages` | 422 | The PDF has more pages than the limit (50). |
| `pdf_too_much_text` | 422 | The PDF has more text than the limit. It is refused, never cut. |
| `pdf_encrypted` | 422 | The PDF is encrypted. |
| `pdf_corrupt` | 422 | The PDF is malformed, truncated or not a PDF. |
| `pdf_no_text` | 422 | The PDF has no extractable text, as a scan has. There is no OCR. |
| `pdf_timeout` | 422 | Reading the PDF took longer than the limit and the child was killed. |
| `pdf_resource_limit` | 422 | The PDF needed more memory or decoded size than allowed, as a bomb does. |
| `unknown_backend` | 422 | The named backend is not the configured one, or none is configured. |
| `hosted_backend_not_confirmed` | 422 | A hosted backend was named without `confirm_hosted`. |
| `budget_exceeded` | 409 | The call would pass the configured budget. |
| `report_refused` | 422 | The report was refused because a claim could not be grounded. |
| `bank_not_found` | 404 | The fact bank file is missing. |
| `bank_invalid` | 422 | The fact bank file is not valid. `details` names the fact and field. |
| `blacklisted` | 409 | The company, board slug or domain is on the blacklist, so it cannot be added to the watchlist. |
| `tombstoned` | 409 | A person denied this company or board earlier. It stays off the watchlist until a person removes the denial. |
| `already_watched` | 409 | The company or the board is already on the watchlist. |
| `already_blacklisted` | 409 | The same normalized company key, slug or domain is already blocked. |
| `http_error` | other | Any other HTTP failure, with a fixed message. |
| `internal_error` | 500 | An unexpected failure. The cause is not in the answer. |

A route raises `ApiError(status, code)` to return its own typed failure.

## Serving the web bundle
If `web/dist` exists (the built Svelte bundle, see [setup.md](setup.md#run-the-web-ui)), the app serves it at `/` with `index.html` as the default. The API routes win over the bundle, and an unknown path under `/api` is still a typed 404. With no bundle, `/` is a typed 404.

### The content security policy
Every answer carries `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'`. The bundle is local files only, so scripts and styles load from this origin, nothing inline is allowed (no `unsafe-inline`, no `unsafe-eval`), the page may call this API and nothing else, and it cannot be framed or change its base. The UI is built to need none of the loosened settings, and `web/scripts/check-dist.mjs` fails the build on an inline script or a remote origin. See [ADR 0038](adr/0038-web-ui-stack-and-csp.md).

## Start it and try it
See [setup.md](setup.md#start-the-api-server) for the commands. The tests are:
```bash
uv run pytest tests/component/test_api_security.py tests/component/test_api_routes.py tests/component/test_api_postings.py tests/component/test_api_facts.py tests/component/test_repository.py tests/component/test_link_posting.py tests/unit/test_api_route_table.py tests/unit/test_api_backends.py tests/unit/test_posting_build.py -q --no-cov
uv run pytest tests/e2e/test_api_server_process.py tests/e2e/test_api_postings_process.py -q --no-cov
```
The component tests drive the real app in process over `httpx.ASGITransport`, with no mocked component. The two e2e files start the real server as a child process on port 5309, so nothing else may be listening there, and fails (never skips) if it cannot.

Two integration tests need more: `uv run pytest tests/integration/test_api_postings_live.py -q -m needs_network` fetches a real public page through the whole API, and `-m live` pastes a fictional posting and analyzes it with a real Ollama and `qwen3.5:0.8b` (see [providers.md](providers.md#try-it-locally)). They fail, never skip, when the network or Ollama is missing.
