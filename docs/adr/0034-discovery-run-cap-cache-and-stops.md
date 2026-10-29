# ADR 0034: The discovery run caps scoring, caches by run id, and stops cleanly

Status: accepted (card H7a). Builds on [ADR 0031](0031-conservative-dedupe-filters-and-closing.md).

## Context

Scoring a listing costs model calls. A refresh of a watchlist can surface far more listings than a person will read, and a local model can go down in the middle of a run.

## Decision

- **The cache key is the run id.** `run_id(text_hash, bank_digest, backend, model)` already exists for provenance. A stored report with that id is the score for any listing with the same text under the same bank, backend and model. No second key is invented, and no table links listings to reports: the id is computed from the listing, so there is one source of truth.
- **Only a complete report is a cache hit.** An incomplete report is shown, flagged, and tried again next run, so a score built from rule ceilings because the model was down does not stick.
- **The cap counts analyzer calls, most recent listings first.** Cache hits are free and do not count. The first listing past the cap stops scoring and the rest are reported as unscored.
- **A backend outage or a spent budget stops scoring.** Provider unavailable and rate limited extraction failures end the run with `stopped_by="backend"`, and `BudgetExceeded` with `"budget"`. Trying every remaining listing against a backend that is down only wastes time. Stored scores are kept and the rest are unscored. Other extraction failures (a refusal, a schema violation for one posting) leave only that listing unscored.
- **The analyzer is injected.** `run_discovery` takes a function from posting to gap report. Production passes `analyze` over the real provider. This keeps the cap, cache and stop rules testable without a model, and the tests still run the real pipeline after extraction.
- **Blacklist, then fetch.** A blacklisted watched company is skipped before any request, and its stored listings are left out of the ranking.
- **Ranking:** score, then recency, then id; rows with no score after scored rows; unscored rows last.

## Consequences

- A refresh with an unchanged board and an unchanged bank makes no model call.
- Changing the model or the bank rescored everything, up to the cap per run.
- The `discovery_report` table grows with every distinct text and identity. A cleanup rule is not part of this card.
- The routes and the refresh button are a separate card (H7b) because they wait on the API foundation (G1).

## Alternatives considered

- **A listing to report link table.** Rejected: it duplicates what the run id already determines.
- **Cache incomplete reports too.** Rejected: an outage would freeze a partial score.
- **Keep scoring after a backend failure.** Rejected: it multiplies timeouts and retries by the number of remaining listings.
