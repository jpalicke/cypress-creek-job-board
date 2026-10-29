# ADR 0041: How company suggestion keeps a model away from the watchlist

Status: accepted (pod decision under Joe P's delegation, card H8; his review pending)

## Decision
- The model sees a tag profile only: each tag name with the highest level any usable fact gives it. No claim text, employer, issuer, role or fact id. `local_only` facts add nothing for a backend that is not local.
- The model answers with names only, in a strict schema of at most 20 strings. The system text never mentions a denied or blocked company, because the filter is code.
- Each name goes through V14, a company key, a repeat check, the denied list and the blacklist, in that order, before any request is made for it. Matching is on `company_key`, so spelling variants of a denied company are denied.
- The resolver, not the model, makes every link: slugs are guessed from the cleaned name in a fixed safe form, and each adapter's `probe` is asked through the polite client. A missing board is kept in an in memory negative cache for 24 hours by default. A failed probe is never cached as missing.
- Evidence is graded: strong when the board reports the company's name (company key equal), weak when it exists and reports no name, none (dropped) when it is missing or reports another company. Weak suggestions reach the user with the grade visible.
- Survivors become pending rows. Approval is the only watchlist write and lives in `review.py`; the model path never imports it, and a test checks the imports. Denial marks the company's pending rows denied, which is the permanent tombstone (company key and board), honored by the filter, the store and `Watchlist.add`.
- `IdentityEvidence` moved to `discovery/evidence.py` (and is still importable from `watchlist`), so the resolver does not import the watchlist module.
- The card names threats T15 to T18; in the spec those ids are the API, feeds, cost and logs. The suggestion threats are T10 to T13, and the docs use those.

## Why
- A model can only be trusted to be wrong in new ways, so everything it says is data until code accepts it: shape (V14), identity (the key), existence (the probe) and a human (the approval).
- Checking the denied list before resolving saves requests, and checking it again after resolving catches a different name that lands on a denied board.
- Putting the writer in its own module makes the boundary testable with an import scan instead of a promise.

## Limits
- V14 is a shape check. A short phrase of plain words passes it, and the resolver drops it only because no board exists for it. A real board with that slug would reach review with weak evidence.
- The negative cache is memory only, so a restart probes again. The Lever region is not stored by this flow.
- `company_key` does not fold a Cyrillic capital EM to Latin M (issue #142), a gap the denied filter inherits.
- Routes for listing, approving and denying suggestions, and the trigger, are the next card because they depend on the API context that the posting routes add. No seed directory yet.
