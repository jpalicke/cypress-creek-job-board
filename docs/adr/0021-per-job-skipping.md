# ADR 0021: Skip a malformed job, report it, and cap the skips

Status: accepted (Joe P, card H3b). Supersedes the "one bad job fails the board" decision in [ADR 0020](0020-adapter-failure-modes.md).

## Context

ADR 0020 failed a whole board when one job was malformed, so that a feed change could never shrink a board silently. The cost was real: one bad job among hundreds blocked every other job on that board until the feed was fixed. The risk it guarded against is also real: jobs missing from a fetch later look closed.

## Decision

- **Each job is validated on its own.** A malformed job is left out of the listings and recorded as a `SkippedJob`: its position in the feed (`index`), its `job_id` only when the feed id is short and plain, the `field` inside the job, and a `reason_code` (`invalid_field`, `empty_text`, `content_too_long`, `content_unreadable`). A skip never holds a feed value or a validator message, because feed text is hostile.
- **`fetch_board` returns `BoardFetch(listings, skipped)`.** The skipped jobs are part of the result, so the caller can log or show them. Nothing is dropped without a record.
- **A skip budget keeps the old guarantee.** If more than 10 percent of a board's jobs are skipped (`MAX_SKIPPED_FRACTION`, checked by `check_skip_budget`), the whole board fails with `FeedSchemaError` for the `jobs` field, exactly as before. A feed wide change breaks every job, so it trips the budget. A single bad job on a board of ten or more passes. On a board of fewer than ten jobs any skip exceeds the budget and fails the board, which is the safe direction.
- **Shape errors above the job level still fail the board.** A body that is not JSON, a missing `jobs` list, or a `jobs` value of the wrong type raises `FeedSchemaError` as before.
- Everything else in ADR 0020 stands: 404 only means missing, a 404 is never cached, description HTML is unescaped exactly once.

## Consequences

- One malformed job no longer blocks a board. It is reported, and the board is usable.
- A caller must read `BoardFetch.skipped`. Treating a fetch with skips as a full snapshot is a caller bug, because a skipped job has no listing and must not be marked closed on that basis.
- The 10 percent figure is a single constant. Changing it is a one line change with a test that names the value.
- The real Stripe board is covered by a live test that the skips stay within budget. The skip and budget behavior itself is covered by unit and component tests on hand written hostile feeds, because a healthy public board has no malformed jobs to exercise it. Mutation checks confirmed those tests go red when the budget or the field handling is broken.

See [the adapter architecture](../architecture.md#board-adapters).
