# ADR 0013: Pinned public HTTP transport

Status: proposed (F1b, pending PR review)

## Decision

- `fetch_url(url, *, limits=FetchLimits())` is the public library entry. It returns `FetchResponse` with the final URL, status, content type and bytes. `UrlGuardError` retains the F1a reason codes; `SafeHttpError` reports transport failures by stable reason code and a generic message.
- Run the fetch in a disposable Python child under one parent deadline. Production always calls `validate_url` in the child. This bounds blocking operating-system DNS along with redirects, response headers and body reading. The parent kills and reaps a child that exceeds the deadline. Process creation and cleanup can still add wall-clock time.
- Use the existing HTTPX dependency. At each hop, validate every DNS answer, then connect to the selected numeric IP while retaining the validated hostname in the `Host` header and HTTPX `sni_hostname` extension for TLS certificate verification. Disable environment trust and automatic redirects, and create a fresh client for each hop. No cookies, URL credentials or JavaScript are used.
- Accept at most three redirects. Check literal redirect text for controls, whitespace and backslashes before joining it, then validate the resulting URL again. Only HTTP and HTTPS on ports 80 and 443 can pass the guard; no configuration or environment value permits private destinations.
- Read the final response with `iter_raw`. Default ceilings are 10 MiB on wire, 10 MiB decoded and a 100:1 decoded-to-wire ratio. Accept identity or one complete gzip stream and HTML, XHTML, plain text or PDF content type. Reject malformed encoding, missing or disallowed type, and non-2xx status. Redirect bodies are not read, so these byte caps govern only the final body.
- Keep direct HTTP-client imports limited to `ingest.safe_http` and the separate `providers.ollama` adapter. The latter consumes operator-configured model endpoints under provider rules, not posting or discovery URLs. A unit test audits static and literal dynamic imports across the source tree.

## Why

Validating a URL and then giving its hostname to a conventional HTTP client would allow a second DNS lookup to choose a different address. Connecting to the validated numeric IP closes that gap while `Host` and TLS SNI retain the requested site's identity. Repeating validation for redirects prevents a public first hop from authorizing a private later hop. Disabling environment proxies prevents an implicit connection path outside the selected IP.

An HTTP client timeout cannot reliably interrupt operating-system DNS. The child process gives the parent a way to stop a blocked lookup. The worker protocol passes a capped response body or known error reasons; remote URLs, bodies, credentials and resolver messages are not included in exception text.

These conservative limits reject some legitimate content and sites that require authentication, unsupported compression or client-side rendering. A user-facing workflow may explain those failures later without weakening the public-address rule.

## Evidence and limits

Unit tests cover coordinates, decoding, limits, worker records and the import restriction. Component tests use real local HTTP servers for headers, redirects, timeouts, size, gzip and isolation. Integration tests fetch public HTTPS with real DNS and certificate checks. A process test uses a real UDP DNS responder that changes answers between queries and real local servers to demonstrate that the first validated IP is the one contacted. Its loopback resolver is confined to the test tree; production has no alternate resolver entry. Public-address validation is independently tested, so the local setup is a compositional rebinding test rather than a production operating-system-DNS end-to-end proof.

See [the fetching architecture](../architecture.md), [the threat model](../threat-model.md), [ADR 0009](0009-url-target-validation.md) and HTTPX's [SNI extension documentation](https://www.python-httpx.org/advanced/extensions/#sni_hostname).
