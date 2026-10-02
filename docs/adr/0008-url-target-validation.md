# ADR 0008: Public URL targets and strict authority parsing

Status: proposed (F1a, pending PR review)

## Decision
- `validate_url(url)` returns a frozen `ValidatedTarget(scheme, host, ip, port)` or a `UrlGuardError` with a stable reason code. The error never includes the submitted URL, credentials or resolver details.
- Use the standard library: `urllib.parse` for splitting, explicit authority checks, `ipaddress` for address classification and `socket.getaddrinfo` for resolution. No HTTP client or dependency is added by this card.
- Accept only HTTP and HTTPS on ports 80 and 443. Reject credentials, literal whitespace, ASCII control characters and backslashes. Brackets must contain an IPv6 literal, not IPvFuture or hostname syntax.
- DNS hostnames use ASCII labels. Normalize case and one trailing dot, but reject Unicode and `xn--` IDN labels, percent-encoded hosts, empty labels and legacy numeric IPv4 spellings. Canonical IPv4 and compressed or expanded IPv6 literals are supported.
- Require globally routable unicast addresses and explicitly reject multicast, reserved, IPv6 site-local, scoped, mapped, 6to4, Teredo and well-known NAT64 addresses. Reject the entire DNS result if any address is unsafe, then select the first validated answer.
- There is no local-network bypass and no config or environment override. The guard is for untrusted posting and discovery URLs, not a replacement for provider configuration.
- The resolver is called once per hostname validation. Its timeout is controlled by the operating system. The returned IP is a transport input, not proof that a caller used it.

## Why
URL splitting alone does not validate an authority. Checking raw host syntax before normalization closes parser ambiguities, and checking all DNS answers avoids selecting a public answer while overlooking a private one. Returning the hostname separately from the IP lets a transport pin its connection without losing Host and TLS identity.

Rejecting IDNs, transition addresses and legacy numeric forms also rejects some legitimate URLs. This is a deliberate compatibility limit rather than an attempt to repair ambiguous input. A future policy expansion requires tests and review.

F1a covers target validation only. F1b owns the HTTP client decision, pinned connections, redirect validation, response limits, timeouts, real rebinding tests and the HTTP-import restriction. Its architecture document will describe the complete fetching path. See [the threat model](../threat-model.md) for the rule and test matrix.
