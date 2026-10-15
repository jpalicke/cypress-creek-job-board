# ADR 0020: Adapter failure modes and description text

Status: accepted (Joe P, card H3). The "one bad job fails the board" decision is superseded by [ADR 0021](0021-per-job-skipping.md).

## Context

An ATS adapter reads a feed the project does not control. Several things can go wrong, and each needs a decision that a caller can rely on: the feed changes shape, the board does not exist, the server refuses the request, one job in a large board is malformed, and the description arrives as HTML that is escaped inside JSON.

The design says a schema change must skip the board with a visible error while other boards continue, and that a 404 marks the watchlist entry broken rather than dropping it silently. The transport originally raised `SafeHttpError` for a 404, so the polite client could not tell a missing board from any other refusal ([ADR 0019](0019-polite-fetch-timing-and-clocks.md)).

## Decision

- **A shape violation names the field and fails the whole board.** The feed models are strict and ignore unknown extra fields. A missing field, a wrong type, an over long value or a job URL that is not http or https raises `FeedSchemaError` with the field path of the first problem, such as `jobs[3].title`. The error carries the path only, never the value or the validator message, because the value is hostile feed text. An empty title, or a description with no text left after extraction, is also a schema error for that field. The caller skips that board and continues with the others.
- **Only a 404 means the board is missing.** The transport passes a 404 through when `pass_through_statuses` is on, and the polite client raises `NotFound`. The adapter turns that into `BoardNotFound` for `fetch_board` and into `ExistenceResult(found=False, organization_name=None)` for `probe`. A 403, a 410 or any other refused status stays a `SafeHttpError` with reason `http_status` and propagates. These can mean a block, a gone account or an outage, and calling them "missing" would mark a healthy watchlist entry broken or hide a real problem.
- **A 404 is never cached.** The client raises before it writes the cache, so a board that is created later is found on the next request, and a made up slug leaves no entry behind.
- **One bad job fails the board (superseded by ADR 0021).** `parse_jobs_response` raises on the first bad job rather than skipping it. Partial results would let a feed change shrink a board silently: the missing jobs would later look closed. Failing loudly keeps the stored state of that board unchanged until the shape problem is understood. Skipping single jobs, with a visible per job warning, is deferred. It would need a result type that carries both listings and skipped jobs, and a rule for when too many skips still fail the board.
- **Description HTML is unescaped exactly once, before `html_to_text`.** The feed holds the description as HTML text whose markup is escaped (`&lt;p&gt;`). One `html.unescape` gives real markup for `html_to_text`, which drops hidden content and scripts. Unescaping again would turn text a candidate wrote, such as a literal `&lt;`, into markup that was never there, and skipping it would leave the whole description as visible tag text. The order is unescape, `html_to_text`, `normalize`, then `text_hash` over the normalized text.

## Consequences

- A caller handles three outcomes per board: listings, `BoardNotFound` (mark broken), or another exception (visible failure, board skipped, run continues). No adapter error echoes a feed value, so logging one is safe.
- (Superseded by ADR 0021.) One malformed job in a board of hundreds blocked that board until the feed is fixed or the model is relaxed. This is the cost of never shrinking a board silently.
- A transient 403 from a rate limiter at the vendor shows up as a loud transport error, not as a broken entry.
- Other ATS adapters follow the same rules: `FeedSchemaError` for shape, `BoardNotFound` only for a 404.
- Tests: the `tests/integration/test_greenhouse_network.py` file covers a real board, a real probe and a real 404 against the live service. Unit tests cover shape violations and hostile text with recorded and hand written feeds.

See [the adapter architecture](../architecture.md#board-adapters) and [the polite fetch layer](../architecture.md#polite-fetching).
