# ADR 0037: Discovery routes

## Status
Accepted (H7b, #137).

## Context
H7a built the discovery run (fetch, filter, score under a cap, cache, rank) as a library. The routes that start a run and read the ranking were left for H7b because they needed the API security layer. They must not change what the library guarantees: a blacklisted board is never fetched, the cap bounds the model calls, and the score is for triage only.

## Decision
- `POST /api/discovery/refresh` calls `run_discovery` and answers its summary. `GET /api/discovery/listings` calls `ranked_listings` and answers the rows read back from storage. Both are under the Host check, and the POST is under the CSRF check, like every other route.
- The request names the backend, as the analyze route does. A name that is not the configured one is refused before anything is fetched, and a hosted backend needs `confirm_hosted`. One budget tracker covers the whole run, so a refresh cannot spend more than the configured budget however many listings it scores.
- The cap defaults to the library's 30 and the request may lower or raise it, to at most 200.
- Filters travel in the refresh body, and as query parameters on the listing route. They are the library's `ListingFilters`, so there is one set of rules and one validator.
- The listing rows never carry the listing text, only the fields a person needs to triage and the `run_id` that names the stored gap report. The answer carries a note that the score is for triage and is not a probability.
- The adapters are a parameter of `create_app`. With none given, `discovery/factory.py` builds the real Greenhouse, Lever and Ashby adapters on the first request, each over its own polite client with its own limits and the fetch settings from the environment. Tests give real adapters pointed at loopback servers. No adapter is replaced by a fake.
- Lever regions stored on watchlist entries are told to the Lever adapter before each run, so a board on the EU host is asked there first.
- A board that fails, or a backend that is down, is a 200 with the failure in the summary (`errors`, `stopped_by`). A report the pipeline refuses is a 422 `report_refused`, as for the analyze route.

## Consequences
- The route does no work the library does not already do; the blacklist, cap, cache and stop rules stay in one place and keep their tests.
- A refresh can take a long time with a real model and many listings. The cap and the budget bound it. It runs in a worker thread, so other requests are served meanwhile, but there is no progress report or cancel; both are future work if the UI needs them.
- The listing route needs the configured backend and the bank to find stored scores, because the score cache key covers both. A changed bank or model shows rows as unscored until the next refresh.

## Reversing
Remove the router and the `adapters` argument; the library is unchanged.
