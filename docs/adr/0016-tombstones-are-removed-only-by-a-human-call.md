# ADR 0016: Denied companies are tombstoned and only an explicit call lifts one

Status: accepted (Joe P, card H1a)

## Decision
- A human denial writes a `suggestion` row in state `denied`. That row is the tombstone. There is no separate tombstone table.
- A company is blocked from the watchlist when a tombstone matches its `company_key` or its board, the pair `(ats, slug)`. The company match uses the one `company_key` normalizer, so a case, suffix or homoglyph variant is caught.
- `Watchlist.add` never lifts a tombstone. Only `Tombstones.remove(name=...)`, a deliberate human action, deletes a company's denied rows.
- Removing a company's tombstone removes its board tombstones with it. A tombstone written for a different company on the same board stays, and keeps blocking that board.
- A company has at most one tombstone. Denying it again keeps the first.

## Why
- A denied row that is the tombstone means one source of truth: the same row records who proposed the company, and why it is blocked.
- Matching by board as well as by key stops a renamed company from getting back in on the same job board.
- Making removal a separate call means a model, a resolver or a repeated approval can never undo a denial by accident. The lift is always a human step, and a later card that exposes it must require a human approval.

## Consequences
- Removal deletes the row, so no history of the denial is kept. If that is wanted later, add an audit table in a new migration.
