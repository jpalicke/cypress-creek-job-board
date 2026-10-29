# ADR 0025: The Lever region is stored on the watchlist entry and seeded back into the adapter

Status: accepted (card #109). Supersedes the "memory only" part of [ADR 0022](0022-lever-pagination-and-region.md).

## Context

`LeverAdapter` finds a board's host by asking US then EU and remembers the answer in memory. A fresh process therefore sends one extra request, a US 404, for every EU board, and a 404 is never cached.

## Decision

- `watchlist_entry` gets a nullable `region` column (migration `0005_watchlist_region.sql`). The database allows only `us` or `eu`, and only on a `lever` board.
- `WatchlistEntry.region` is a `LeverRegion` or `None`. The entry refuses a region on any other ATS with `InvalidBoard`.
- `Watchlist.set_region(ats, slug, region)` records the host after a successful probe or fetch and returns whether the board is watched.
- `LeverAdapter.remember_region(slug, region)` seeds the in-memory map from a stored region. The adapter still keeps no state on disk and still forgets a region when its host answers 404, so a board that moved is found again by a fresh `probe`.

## Consequences

- A caller reads `region_of` after a successful fetch, stores it with `set_region`, and on the next run seeds each Lever entry with `remember_region` before fetching. The scan card H8 (#47) is the first caller. Nothing calls them yet.
- A stored region that has gone stale costs one 404 and a report of a missing board, never a wrong listing.

- `discovery/watchlist.py` imports `LeverRegion` and the `lever` name from the Lever adapter module. That is one vendor adapter in a state module. If a second ATS with regions appears, move the region type and the name into a small shared module.
- Tests cover every tier: unit (entry rule, seed normalization), component (SQLite, CHECK, loopback servers), e2e (a region written by one process and used by a fresh one, which asks exactly one host) and integration (a seeded region reaches the real EU host with no US request, run by the network tests).

## Alternatives considered

- **Put the region on `ExistenceResult`.** Rejected for the reason in ADR 0022: it widens the contract of every adapter for one vendor.
- **Let the adapter read the database.** Rejected. Adapters stay pure over the polite client.
