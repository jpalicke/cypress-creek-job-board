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

## Not yet limited
There is no request body size limit in this card, because it has no route that reads a body. The first write route (G2) brings a limit with it, and no write route may ship without one.

## Routes
| Route | Answer |
| --- | --- |
| `GET /api/health` | `{"status": "ok", "backends": [{"provider", "model", "reachable"}]}`. `reachable` is `reachable` when the backend address returns any HTTP answer within 2 seconds, `unreachable` when it does not, and `not_checked` for a backend that cannot be probed yet (everything except Ollama). With no backend configured, `backends` is empty. |
| `GET /api/providers` | `{"providers": [{"provider", "model", "local", "strict_schema", "context_tokens", "cost_per_mtok": {"input", "output"}}]}`. Never a key, an environment variable name or a URL. |
| `GET /api/session` | `{"csrf_token": "..."}`. |

Posting and analyze routes arrive in G2, and the draft help route later.

## Error codes
| Code | Status | Meaning |
| --- | --- | --- |
| `host_not_allowed` | 403 | The Host header is not one of the two loopback names on port 5309. |
| `csrf_token_invalid` | 403 | A write came without the session token, or with a wrong one. |
| `not_found` | 404 | No such route or file. |
| `method_not_allowed` | 405 | The path exists but not for this method. This includes CORS preflights. |
| `invalid_request` | 422 | The body or query did not match the route's model. `details` lists each `field` and a `problem`, never the submitted value. |
| `http_error` | other | Any other HTTP failure, with a fixed message. |
| `internal_error` | 500 | An unexpected failure. The cause is not in the answer. |

A route raises `ApiError(status, code)` to return its own typed failure.

## Serving the web bundle
If `web/dist` exists (the built Svelte bundle from card G3), the app serves it at `/` with `index.html` as the default. The API routes win over the bundle, and an unknown path under `/api` is still a typed 404. With no bundle, `/` is a typed 404.

## Start it and try it
See [setup.md](setup.md#start-the-api-server) for the commands. The tests are:
```bash
uv run pytest tests/component/test_api_security.py tests/component/test_api_routes.py tests/unit/test_api_route_table.py -q --no-cov
uv run pytest tests/e2e/test_api_server_process.py -q --no-cov
```
The component tests drive the real app in process over `httpx.ASGITransport`, with no mocked component. The e2e file starts the real server as a child process on port 5309, so nothing else may be listening there, and fails (never skips) if it cannot.
