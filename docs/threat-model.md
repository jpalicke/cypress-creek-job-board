# Threat model

The full design threat model is in [spec.md, section 9](spec.md#9-threat-model). This page records the implemented URL boundary, the remaining SSRF controls and the prompt structure. It does not claim that the complete fetching path exists.

## SSRF boundary

A posting link or discovery URL is hostile input. It must not cause a connection to a local service, private network or cloud metadata endpoint. F1a implements `validate_url` in `src/cypress_creek/ingest/url_guard.py`; F1b supplies the guarded HTTP transport. URL validation alone cannot prevent DNS rebinding if a caller later resolves the hostname again.

| Rule | Enforcement |
| --- | --- |
| Only `http` and `https`, ports 80 and 443, no URL credentials | Implemented in F1a |
| Reject literal whitespace, ASCII controls and backslashes before parsing | Implemented in F1a |
| Check raw hostname syntax before case normalization; require valid IPv6 inside brackets | Implemented in F1a |
| Canonical public IPv4 or IPv6 only; reject private, loopback, link-local, multicast, reserved, unspecified, shared and metadata addresses | Implemented in F1a |
| Reject scoped, IPv4-mapped, site-local, 6to4, Teredo and well-known NAT64 IPv6 addresses | Implemented in F1a |
| Resolve a hostname once and reject the whole answer set if any address is unsafe | Implemented in F1a |
| Connect directly to the validated IP, keeping the hostname for Host and TLS certificate/SNI checks | Pending F1b |
| Follow redirects manually, at most three, validating every hop | Pending F1b |
| Stream with byte and decompression-ratio caps, a content-type allow list, connect and total timeouts | Pending F1b |
| Fetch without cookies, credentials or JavaScript execution | Pending F1b; F1a makes no HTTP request |
| Restrict HTTP client imports to reviewed modules and prove connection pinning with real DNS/server tests | Pending F1b |

`validate_url(url)` returns a frozen `ValidatedTarget` containing `scheme`, `host`, `ip` and `port`. The hostname is lowercased and one trailing dot is removed; IP literals are canonicalized. A future transport must use the IP for the connection, handle the original path/query consistently, omit the fragment and repeat validation for every redirect. Merely constructing a `ValidatedTarget` yourself is not validation.

No flag, config field or environment variable can permit a private destination. The separate provider configuration has its own loopback and remote opt-in rules; changing it does not change this guard.

## Rejection reasons

Every rejection raises `UrlGuardError`. Branch on `reason_code`, not the message. The message is always `URL rejected by the network safety policy`, with no URL, credentials or underlying resolver message.

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
- Paths and queries are not decoded or turned into HTTP request lines here. The literal-character check covers ASCII controls and Unicode whitespace, not every Unicode control category. F1b must preserve encoded path/query data without turning it into protocol syntax.
- DNS uses the real operating system resolver, whose timeout is not bounded by this function. F1b must account for resolution in its timeout design.
- The result is not an HTTP response. Pinned connections, TLS verification, redirects, response limits and rebinding resistance remain unverified until F1b lands.

The choices are recorded in [ADR 0009](adr/0009-url-target-validation.md). Python's [URL parser documentation](https://docs.python.org/3.13/library/urllib.parse.html#url-parsing-security) explains why parsing needs additional validation. The all-address check follows [OWASP's SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html).

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

## Tests

| Tier | Evidence |
| --- | --- |
| Unit | Hostile URL/reason table, IPv4 and IPv6 Hypothesis properties, malformed-input handling, immutable targets and mixed public/private address rejection |
| Component | Real machine hostname resolves to a nonpublic address and is rejected; public target literals work with numeric-only OS address lookup |
| Integration (`needs_network`) | Real public DNS resolution, hostname case/trailing-dot normalization, and a real failed lookup with a redacted exception |
| End to end | A separate Python consumer receives a public target or a typed, redacted rejection |

Run the local URL tests (the component tier requires the machine's hostname to resolve to at least one nonpublic address):

```bash
uv run pytest tests/unit/test_url_guard.py tests/component/test_url_guard_resolver.py tests/e2e/test_url_guard_process.py -q
```

Run the public-DNS tests with working network access. An unavailable resolver fails loudly:

```bash
uv run pytest tests/integration/test_url_guard_dns.py -q
```

Run all tiers with the project coverage gate:

```bash
uv run pytest --cov --cov-fail-under=80 -q
```

There are no mock resolvers or providers. Hostile address lists are data supplied directly to a pure validator. A public HTTPS fetch, real DNS-rebinding arrangement, local HTTP server tests and browser flows are not established by these tests; the first three belong to F1b and browser flows await the UI.

## Prompt structure (T1 to T4)

Posting text is hostile (injection, instruction override, omission, fact extraction). Code is `src/cypress_creek/pipeline/prompt.py`, the behavior is in [pipeline.md](pipeline.md#prompt-builder).

- **Three blocks.** The system message is trusted and static and holds no posting text and no facts. The data block holds the posting and nothing else. The facts block is trusted and separate, and only for stages that need facts.
- **Random boundary.** Each call wraps the posting in a boundary with a token from `secrets` (128 bits). The token is checked against the posting and replaced if it clashes. A fake closing line in the posting cannot match a token the attacker has not seen.
- **No bank in extraction.** The extraction prompt shows the model no facts (T4). Later stages see only the candidate facts for one requirement.
- **Fact filter.** Only verified facts are rendered, and `local_only` facts never go to a hosted backend.
- **Not a defense on its own.** A model can be talked out of any boundary. The deterministic validators after the model (V1 to V14) are the control, and the human review is the last one. Do not add prompt wording to cover for a missing validator.

Tests: `tests/unit/test_prompt.py` covers fake closing delimiters, a token clash, hostile postings never reaching the system message, the fact filter and a Hypothesis property that any posting sits between exactly one opening and one closing boundary. Run it with `uv run pytest tests/unit/test_prompt.py -q`. Model level injection resistance is measured by the eval harness, not here.
