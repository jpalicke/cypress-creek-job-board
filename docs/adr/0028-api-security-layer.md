# ADR 0028: The API security layer: an exact Host allow-list, an app-wide CSRF dependency, a session route and no schema routes

Status: accepted (card G1). Security card: the Host and CSRF logic wants a second human review.

## Context

The API is a local service, so the threats are other machines, DNS rebinding (T15) and cross-site request forgery from a page the user visits (T10, T11). The design fixes the rules: loopback bind on 5309, a Host check, a per-session token on writes, no CORS and one typed error shape.

## Decision

- **The Host check is an exact allow-list in a pure ASGI middleware.** The two values are `127.0.0.1:5309` and `localhost:5309`. The request must carry exactly one Host header, so a duplicate (a smuggling trick) fails. It is added last so it is outermost, runs before routing and the token check, and covers unknown paths and the static bundle. It answers the typed error itself, because errors raised inside a plain middleware do not reach exception handlers.
- **The CSRF check is a dependency of the whole app.** `FastAPI(dependencies=[...])` covers every route added later, including ones from other cards, with no per-route code. It checks the method, so reads need no token. The token is `secrets.token_urlsafe(32)`, made when the app is built and kept only in memory. Comparison uses `hmac.compare_digest`. A write to a path with no route is a 404 and never reaches the check, since there is nothing to write to.
- **The UI gets the token from `GET /api/session`.** The design allowed the HTML shell or a GET that sets no cookie. The route works with or without the bundle, and a cookie would add the ambient authority CSRF abuses. The Host check and the lack of CORS keep other origins from reading it.
- **No CORS, and no docs or schema routes.** `/docs`, `/redoc` and `/openapi.json` are off so the route table is exactly the routes written. The route table test reads the app's own schema, so it needs no private FastAPI classes.
- **The error shape is one pydantic model with fixed messages.** Handlers cover the app's own errors, HTTP errors, request validation (field paths and rule text only, never the input) and any other exception. Starlette's own error text is never copied into an answer.
- **The server refuses a non loopback bind.** `CYPRESS_CREEK_API_HOST` may name a loopback IP address and anything else exits with code 2 before listening. The port is fixed at 5309 because the Host allow-list names it. There is no `allow_remote` setting.
- **Provider settings are required to start.** The server reads them with `load_settings`. The app factory also takes `None`, which lists no backend, so the routes can be tested without one.
- **Tests use `httpx.ASGITransport`.** Starlette's `TestClient` now warns that it wants a new dependency (`httpx2`), and the repo treats warnings as errors. The ASGI transport drives the real app in process with nothing mocked, and an e2e test starts the real server process.

## Consequences

- A later route cannot forget the token or the Host check.
- The token changes at every server start, so a UI must read it after a restart.
- The health route probes a backend address with a short GET on each call, which costs up to two seconds when a backend hangs.
- A hostile name for `Host` that is the same as an allowed one after casefolding is accepted (`LOCALHOST:5309`), which is how HTTP names compare.

## Alternatives considered

- Embed the token in the HTML shell only. Rejected: it breaks without a bundle and makes the API depend on the web build.
- A cookie for the token. Rejected, see above.
- `TrustedHostMiddleware`. Rejected: it allows wildcard patterns, it matches on the host without the port, and its error text is not our typed shape.
- Check the token in a middleware. Rejected: a dependency can read the matched route and returns the typed error through the normal handler.
