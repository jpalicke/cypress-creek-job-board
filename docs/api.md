# The local API

A FastAPI app that serves JSON (and, later, the built web bundle) to the browser on the same machine. It is a local tool and must never be reachable from other machines or from a hostile web page the user happens to visit (threats T10, T11 and T15 in the [threat model](threat-model.md)). Every route inherits the rules below. The code is in `src/cypress_creek/api/`.

## Rules every route inherits
| Rule | How it is enforced |
| --- | --- |
| Loopback only | `uv run cypress-creek-api` binds to `127.0.0.1` on port 5309. `CYPRESS_CREEK_API_HOST` exists only so a wrong value can be refused: anything but `127.0.0.1` (including `127.0.0.2`, `::1`, `localhost` and `0.0.0.0`) stops the server with exit code 2 before it listens. There is no `allow_remote` setting for the API. |
| Host check | `HostCheckMiddleware` runs before everything else. The request must carry exactly one `Host` header equal to `127.0.0.1:5309` or `localhost:5309`. Any other name, a different port, a missing port, a second Host header or a non ASCII value gets a typed 403 `host_not_allowed`. This blocks DNS rebinding. |
| CSRF token on writes | Every request except `GET`, `HEAD` and `OPTIONS` needs the header `X-CSRF-Token`, exactly once, with the session token. That includes `POST`, `PUT`, `PATCH`, `DELETE` and any unusual method such as `PURGE`. It is compared with `hmac.compare_digest`. A missing, repeated or wrong token gets a typed 403 `csrf_token_invalid`. The check is middleware after the Host check, so it covers every route, mounted sub-apps, unknown paths and static files alike. |
| Hardening headers | Every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`. Every `/api` answer also carries `Cache-Control: no-store`, so the session token is never cached. The static bundle is not marked no-store. |
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

| `POST /api/postings` | Adds a posting. Send `Content-Type: application/json` with `{"source": "paste", "text": "..."}` or `{"source": "link", "url": "https://..."}`; the answer (201) has the new `id`, the normalized `text`, its `text_hash`, `warnings` (such as `control_chars_stripped`), `extraction_warnings` (HTML, such as `hidden_elements_removed`), `fetch_warnings` (such as `cross_host_redirect`), `origin_url` and `created_at`. A link goes through the SSRF guard and the polite fetch limits. A raw body with `Content-Type: application/pdf` is checked for size and the `%PDF-` marker and then answered with `pdf_extraction_unavailable`, because PDF text extraction (card F4) is not built yet. |
| `GET /api/postings/{id}/estimate` | What the extraction call would use at most under the configured budget: `{"covers": "extraction", "requests", "input_tokens", "output_tokens", "usd"}`. Nothing is sent to the backend. One entailment call per requirement follows an analysis and is not in this number. |
| `POST /api/postings/{id}/analyze` | Body `{"backend": "<configured provider name>", "confirm_hosted": false}`. Runs the pipeline and answers 200 with `{"report_id", "report"}` where `report` is the `GapReport`. The report may be incomplete: with the backend down it is `status: "incomplete"`, has no score and `incomplete_reasons` says `extraction failed: provider_unavailable`. It is never a 500. A hosted backend needs `confirm_hosted: true`. |
| `GET /api/reports/{id}` | A stored report: `{"report_id", "posting_id", "created_at", "report", "validator_verdicts": [{"stage", "subject", "validator", "passed", "reason"}]}`. The verdicts are those of V4, V5 and V9 over the finished report, without any offending text. |
| `GET /api/facts` | The fact bank from the bank file (`CYPRESS_CREEK_BANK`, default `facts.private/bank.yaml`): `{"facts": [...], "unverified_ids": [...]}`. A missing file is `bank_not_found`. |
| `POST /api/facts/validate` | Body `{"yaml": "<bank file text>", "strict": false}`. Always 200: `{"valid", "fact_count", "unverified_ids", "problem"}` where `problem` is `null` or `{"fact_id", "field", "reason"}`. Strict mode also refuses an unverified fact. The YAML is never echoed. |

The draft help route arrives later (G4 and D7).

### How the routes behave
- **Budget.** Each analysis gets a fresh budget from the provider settings (`max_requests`, `max_usd` and the token limits), checked before every call. A call that would pass it stops with `budget_exceeded` (409) before anything is sent. The budget is per request, not saved across requests.
- **Hosted backends** are never the silent default. The request names the configured backend, a name that is not the configured one is `unknown_backend`, and a backend that is not local needs `confirm_hosted: true` or the answer is `hosted_backend_not_confirmed`.
- **Facts the backend may see.** The pipeline drops `local_only` facts from the prompt for any backend that is not local, the same as everywhere else.
- **No leaks.** No answer contains a key, an environment value, a stack trace or raw remote content. A link that fails says only that it failed and, for a policy block, the stable reason code.

### Body size limits
A body without a declared `Content-Length` (chunked) is refused with `length_required` (411). A body over 1 MiB is `payload_too_large` (413), and a PDF upload may be up to 10 MiB. The check uses the declared length before the body is read. Pasted text is also capped at 50,000 characters by the normalizer (`posting_too_long`).

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
| `length_required` | 411 | The body did not declare its length. |
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
| `pdf_extraction_unavailable` | 501 | PDF text extraction is not built yet. |
| `unknown_backend` | 422 | The named backend is not the configured one, or none is configured. |
| `hosted_backend_not_confirmed` | 422 | A hosted backend was named without `confirm_hosted`. |
| `budget_exceeded` | 409 | The call would pass the configured budget. |
| `report_refused` | 422 | The report was refused because a claim could not be grounded. |
| `bank_not_found` | 404 | The fact bank file is missing. |
| `bank_invalid` | 422 | The fact bank file is not valid. `details` names the fact and field. |
| `http_error` | other | Any other HTTP failure, with a fixed message. |
| `internal_error` | 500 | An unexpected failure. The cause is not in the answer. |

A route raises `ApiError(status, code)` to return its own typed failure.

## Serving the web bundle
If `web/dist` exists (the built Svelte bundle from card G3), the app serves it at `/` with `index.html` as the default. The API routes win over the bundle, and an unknown path under `/api` is still a typed 404. With no bundle, `/` is a typed 404.

## Start it and try it
See [setup.md](setup.md#start-the-api-server) for the commands. The tests are:
```bash
uv run pytest tests/component/test_api_security.py tests/component/test_api_routes.py tests/component/test_api_postings.py tests/component/test_api_facts.py tests/component/test_repository.py tests/component/test_link_posting.py tests/unit/test_api_route_table.py tests/unit/test_api_backends.py tests/unit/test_posting_build.py -q --no-cov
uv run pytest tests/e2e/test_api_server_process.py tests/e2e/test_api_postings_process.py -q --no-cov
```
The component tests drive the real app in process over `httpx.ASGITransport`, with no mocked component. The two e2e files start the real server as a child process on port 5309, so nothing else may be listening there, and fails (never skips) if it cannot.

Two integration tests need more: `uv run pytest tests/integration/test_api_postings_live.py -q -m needs_network` fetches a real public page through the whole API, and `-m live` pastes a fictional posting and analyzes it with a real Ollama and `qwen3.5:0.8b` (see [providers.md](providers.md#try-it-locally)). They fail, never skip, when the network or Ollama is missing.
