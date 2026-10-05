# Threat model

The full design threat model is in [spec.md, section 9](spec.md#9-threat-model). This page records the URL, HTTP transport, posting fetch and HTML content boundaries, and the prompt structure. A user-facing app workflow remains a later card.

## HTML content boundary

Fetched HTML is hostile input. `html_to_text` parses only the supplied bytes, never executes JavaScript and never loads linked resources. It drops script, style, noscript, template, head, meta and comment content, plus elements hidden with supported attributes or inline CSS. A warning counts the hidden elements removed. A 10 MiB input cap and 128-element depth cap reject oversized or deeply nested pages with typed errors. Headings and list items remain separate lines for later requirement extraction. See [ADR 0016](adr/0016-html-text-parsing.md) and [pipeline usage](pipeline.md#html-posting-text).

This is a best-effort visibility filter, not a browser layout engine. It cannot evaluate external stylesheets, CSS selectors, inherited style, media queries or script-rendered content. A page whose posting appears only after JavaScript may yield no posting text; callers must offer manual paste rather than treat an empty extraction as a valid posting. The extracted text remains untrusted and goes through normalization and the downstream validators.

## SSRF boundary

A posting link or discovery URL is hostile input. It must not cause a connection to a local service, private network or cloud metadata endpoint. F1a implements `validate_url` in `src/cypress_creek/ingest/url_guard.py`; F1b's `fetch_url` in `src/cypress_creek/ingest/safe_http.py` uses its selected IP for the actual connection. F2b's `fetch_posting` calls only that guarded transport, with no alternate resolver or HTTP client. See [the fetching architecture](architecture.md) and [setup guide](setup.md).

| Rule | Enforcement |
| --- | --- |
| Only `http` and `https`, ports 80 and 443, no URL credentials | Implemented in F1a |
| Reject literal whitespace, ASCII controls and backslashes before parsing | Implemented in F1a |
| Check raw hostname syntax before case normalization; require valid IPv6 inside brackets | Implemented in F1a |
| Canonical public IPv4 or IPv6 only; reject private, loopback, link-local, multicast, reserved, unspecified, shared and metadata addresses | Implemented in F1a |
| Reject scoped, IPv4-mapped, site-local, 6to4, Teredo and well-known NAT64 IPv6 addresses | Implemented in F1a |
| Resolve a hostname once and reject the whole answer set if any address is unsafe | Implemented in F1a |
| Connect directly to the validated IP, keeping the hostname for Host and TLS certificate/SNI checks | Implemented in F1b |
| Follow redirects manually, at most three, validating every hop | Implemented in F1b |
| Stream with byte and decompression-ratio caps, a content-type allow list, connect and total timeouts | Implemented in F1b |
| Fetch without cookies, credentials or JavaScript execution | Implemented in F1b |
| Restrict HTTP client imports to reviewed modules; prove IP pinning with real DNS/server tests | Implemented in F1b |
| Map a one-off posting link to bounded bytes or a typed, redacted failure | Implemented in F2b |

`validate_url(url)` returns a frozen `ValidatedTarget` containing `scheme`, `host`, `ip` and `port`. The hostname is lowercased and one trailing dot is removed; IP literals are canonicalized. The transport connects to this IP, keeps the hostname for Host and TLS verification, omits fragments and revalidates every redirect. Merely constructing a `ValidatedTarget` yourself is not validation.

No flag, config field or environment variable can permit a private destination. The separate provider configuration has its own loopback and remote opt-in rules; changing it does not change this guard.

## Rejection reasons

At the URL guard boundary, a rejection raises `UrlGuardError`. Branch on `reason_code`, not the message. The message is always `URL rejected by the network safety policy`, with no URL, credentials or underlying resolver message. `fetch_posting` maps this to `BlockedByPolicy` and preserves the stable reason code.

| Code | Meaning |
| --- | --- |
| `invalid_url` | Missing authority, disallowed literal characters or malformed authority/bracket syntax |
| `unsupported_scheme` | Scheme other than HTTP or HTTPS |
| `credentials` | User information in the URL authority |
| `unsupported_port` | Port text other than `80` or `443`, including empty or zero-padded text |
| `ambiguous_host` | Encoded, scoped, non-ASCII, IDN, malformed DNS or legacy numeric host syntax |
| `unsafe_address` | A forbidden literal or resolved address, or a localhost name |
| `dns_failure` | Resolver failure, no addresses, malformed address data or an unsupported address family |

## Compatibility and remaining limits

- ASCII DNS labels only. Unicode and `xn--` IDN labels are rejected, including lookalikes. Ordinary hostname case and one trailing dot are normalized.
- Decimal-integer, octal, hexadecimal and shortened IPv4 spellings are rejected rather than repaired. For example, `2130706433`, `0177.0.0.1` and `0x7f.1` cannot pass through to a resolver. IP literals with a trailing dot are also refused.
- Only exact explicit port strings `80` and `443` are accepted. Either is permitted with either supported scheme; an omitted port defaults to 80 for HTTP or 443 for HTTPS.
- IPv6 mapped and transition mechanisms are refused even when their embedded IPv4 is public. This is deliberately conservative.
- Paths and queries are not decoded by the guard. The literal-character check covers ASCII controls and Unicode whitespace, not every Unicode control category. The transport preserves encoded data in the HTTP request target; HTTPX handles request framing.
- The guard's operating-system DNS call has no independent timeout. The transport runs it in a child process under the whole-fetch deadline. OS process creation and cleanup can add latency beyond the configured deadline.
- The final body defaults to 10 MiB wire, 10 MiB decoded and a 100:1 decompression ratio. Redirect bodies are not read. Only identity or one complete gzip stream is allowed. Only HTML, XHTML, plain text and PDF content types are accepted by default, and a missing content type is rejected.
- The public entry does not execute JavaScript or forward cookies or URL credentials. `fetch_posting` maps HTTP 401 to `NeedsBrowser` and a zero-byte body to `Empty`, both with manual-paste guidance. Other statuses, including HTTP 403, are `FetchFailed`. Successful HTML is returned as bytes. The separate HTML extractor cannot recover posting text that only client-side scripts render; offer manual paste when extraction is empty.

The choices are recorded in [ADR 0009](adr/0009-url-target-validation.md), [ADR 0013](adr/0013-pinned-http-transport.md) and [ADR 0015](adr/0015-link-fetch-browser-signals.md). Python's [URL parser documentation](https://docs.python.org/3.13/library/urllib.parse.html#url-parsing-security) explains why parsing needs additional validation. The all-address check follows [OWASP's SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html). HTTPX documents [IP connection with separate Host and TLS hostname](https://www.python-httpx.org/advanced/extensions/#sni_hostname).

## Try it locally

From the repository root, inspect a target without making a DNS lookup or HTTP request:

```bash
uv run python -c "from cypress_creek.ingest.url_guard import validate_url; print(validate_url('https://1.1.1.1/'))"
```

Expected: `ValidatedTarget(scheme='https', host='1.1.1.1', ip='1.1.1.1', port=443)`.

Check a rejected destination without echoing its URL:

```bash
uv run python -c "
from cypress_creek.ingest.url_guard import UrlGuardError, validate_url
try:
    validate_url('http://127.0.0.1/')
except UrlGuardError as error:
    print(error.reason_code)
"
```

Expected: `unsafe_address`.

Fetch a public page through the guarded transport (requires public network access):

```bash
uv run python -c "from cypress_creek.ingest.safe_http import fetch_url; r = fetch_url('https://example.com/'); print(r.status, r.content_type, len(r.body))"
```

Expected: a `200` status, `text/html`, and a positive byte count. This is a library call, not an app workflow.

## Tests

| Tier | Evidence |
| --- | --- |
| Unit | Hostile URL/reason table, IP properties, malformed input and address sets; transport coordinates, bounded decoding, limits, redacted worker protocol and HTTP-import audit |
| Component | Real local HTTP servers exercise redirects, Host and request path, cookies, type, size, gzip ratio and deadlines; posting fetch tests cover typed errors, provenance and production loopback refusal |
| Integration (`needs_network`) | Real public DNS and HTTPS fetch with certificate verification, plus public posting HTML and PDF through `fetch_posting` |
| End to end | Separate processes consume the public guard and posting fetcher; a real UDP DNS responder alternates loopback answers while the test-only worker connects to the first resolved IP |

Run local guard and transport tests (the URL component tier requires the machine's hostname to resolve to at least one nonpublic address):

```bash
uv run pytest tests/unit/test_url_guard.py tests/unit/test_safe_http.py tests/component/test_url_guard_resolver.py tests/component/test_safe_http_transport.py tests/component/test_fetch.py tests/e2e/test_url_guard_process.py tests/e2e/test_safe_http_rebinding.py tests/e2e/test_fetch_process.py -q
```

Run the public-DNS tests with working network access. An unavailable resolver fails loudly:

```bash
uv run pytest tests/integration/test_url_guard_dns.py tests/integration/test_safe_http_network.py tests/integration/test_fetch_network.py -q
```

Run all tiers with the project coverage gate:

```bash
uv run pytest --cov --cov-fail-under=80 -q
```

There are no mock resolvers or providers. Hostile address lists are data supplied directly to a pure validator. The loopback test resolver is isolated in the test tree and is unreachable through production arguments, config or environment. The rebinding arrangement demonstrates connection pinning with a real local DNS responder and server; public-address validation is independently tested. Browser flows await the UI.

## Prompt structure (T1 to T4)

Posting text is hostile (injection, instruction override, omission, fact extraction). Code is `src/cypress_creek/pipeline/prompt.py`, the behavior is in [pipeline.md](pipeline.md#prompt-builder).

- **Three blocks.** The system message is trusted and static and holds no posting text and no facts. The data block holds the posting and nothing else. The facts block is trusted and separate, and only for stages that need facts.
- **Random boundary.** Each call wraps the posting in a boundary with a token from `secrets` (128 bits). The token is checked against the posting and replaced if it clashes. A fake closing line in the posting cannot match a token the attacker has not seen.
- **No bank in extraction.** The extraction prompt shows the model no facts (T4). Later stages see only the candidate facts for one requirement.
- **Fact filter.** Only verified facts are rendered, and `local_only` facts never go to a hosted backend.
- **Not a defense on its own.** A model can be talked out of any boundary. The deterministic validators after the model (V1 to V14) are the control, and the human review is the last one. Do not add prompt wording to cover for a missing validator.

Tests: `tests/unit/test_prompt.py` covers fake closing delimiters, a token clash, hostile postings never reaching the system message, the fact filter and a Hypothesis property that any posting sits between exactly one opening and one closing boundary. Run it with `uv run pytest tests/unit/test_prompt.py -q`. Model level injection resistance is measured by the eval harness, not here.
