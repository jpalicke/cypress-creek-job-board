# ADR 0036: The watchlist is written only through a human approval marker, and the blacklist wins

Status: accepted (card H1c). Builds on [ADR 0017](0017-tombstones-are-removed-only-by-a-human-call.md) and [ADR 0028](0028-api-security-layer.md).

## Context

The watchlist decides which companies discovery fetches, and a model can propose company names. Nothing a model proposes may reach the watchlist without a person, and a company on the blacklist must never be fetched.

## Decision

- **The request carries a human approval marker and nothing else is accepted.** `POST /api/watchlist` requires `"approval": "human_confirmed"` and refuses any extra field with `extra="forbid"`. There is no field for a proposer or a state, so a suggestion cannot be passed through as if a person had approved it. The suggestion flow (H8) will end in this route, called after a person clicks. The marker is not authentication (the CSRF token and the loopback rules are), it makes the intent explicit and testable.
- **The server stamps the approval time.** The request has no `approved_at`, and sending one is a 422. `Watchlist.add` still takes the time as an argument; the route reads the clock once.
- **The blacklist is checked first, and wins.** A name or board that the filter blocks is `blacklisted` (409) before the watchlist guard runs, by the same `is_blacklisted` function the discovery run uses, so a case, suffix or homoglyph variant is refused.
- **Conflicts are typed 409s with fixed text.** `blacklisted`, `tombstoned`, `already_watched` and `already_blacklisted` never echo the submitted name, the denial, or who proposed it.
- **A name or board that cannot be keyed is a 422** with a fixed field and problem, not an echo of the value.
- **Hostile names are data.** Names are stored and returned as JSON strings, with the `nosniff` header on every answer. No route renders them.
- **No route removes a tombstone or a watchlist entry here.** Removing a denial stays a separate human action (ADR 0017), and removing a watchlist entry has no route yet.
- **Blacklist values are normalized by the filter's own rules.** The route builds a `BlacklistEntry`, so the stored value is what the filter compares, and a variant is a duplicate.

## Consequences

- The UI (G-lane) and the suggestion flow (H8) both call one route with one rule.
- A client that needs to correct an entry deletes the blacklist row and adds it again. Removing a watchlist entry is a later card.
- Bodies are bounded by the API body limit (1 MiB), and every field has its own length cap.

## Alternatives considered

- **A `proposed_by` field the route rejects when it names a model.** Rejected: a string a client controls proves nothing, and a missing field is the stronger rule.
- **Check the blacklist inside `Watchlist.add`.** Rejected for now: the watchlist module would depend on the blacklist repository. The route composes the two, as the discovery run does.
