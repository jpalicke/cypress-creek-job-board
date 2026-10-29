# ADR 0023: Ashby drops unlisted jobs and counts them, probes by the shape of the board, and revalidates with its weak ETag

Status: accepted (Joe P, card H5). Builds on [ADR 0020](0020-adapter-failure-modes.md) and [ADR 0021](0021-per-job-skipping.md), which still apply to Ashby.

## Context

The Ashby job board feed is `GET /posting-api/job-board/{name}`. It returns one JSON object with a `jobs` list and no paging, and it has no limit parameter, so a board is one response. The feed carries no company name, so the board name is the only identity. Every job says whether it is listed (`isListed`), and a job that is not listed is not meant to be shown on the public board. A missing board answers HTTP 404 with a `text/plain` body.

These were checked live on 2026-10-19. A real board of 63 jobs with full descriptions measured 1.95 MB. The response carries `Cache-Control: public, max-age=60` and a weak ETag of the form `W/"job-board:..."`. All 63 jobs of that board were listed, so no live board exposed an unlisted job.

## Decision

- **An unlisted job is dropped and counted, not skipped.** A job whose `isListed` is the JSON value `false` is neither a listing nor a `SkippedJob`. It is counted in `BoardFetch.unlisted`, a field of the shared contract that defaults to `0`. The check runs before any other validation of the job, so a job the feed marks as unlisted cannot cause a skip through its other fields. A look alike value such as `0` or `"false"` is left to validation and rejected, and a job with no `isListed` at all is malformed and skipped, never assumed listed.
- **The skip budget is counted over the listed jobs.** `check_skip_budget` receives the number of jobs minus the unlisted ones. Dropping a job on purpose is not a feed fault, so a board that is mostly unlisted is not a schema failure, and unlisted jobs cannot dilute the 10 percent figure of ADR 0021 either.
- **`probe` checks the shape of the board and not each job.** A 404 is `found=False`. A 200 whose body is a JSON object with a `jobs` list, which may be empty, is `found=True` with `organization_name=None`. A 200 of any other shape raises `FeedSchemaError`, so it is never reported as a board. The individual jobs are not read, because a malformed job is a skip for `fetch_board` to count.
- **`probe` reads the whole board from the same URL as `fetch_board`.** There is no limit parameter to ask for less. Because the URL is the same, the polite client's cache serves the `fetch_board` that follows, so a probe followed by a fetch is one download.
- **The weak ETag is stored and sent back unchanged.** `PoliteClient` keeps the ETag it received, `W/"job-board:..."` included, and sends it as `If-None-Match`. The real server answers 304 to that weak tag, which the live test `test_the_real_server_answers_a_weak_etag_revalidation_with_304` proves against the real host. Nothing in the polite layer needed to change for Ashby. A 304 and a hit inside the refresh window both report `from_cache` as true, with status 304 and status 200 respectively.
- **A 404 is a missing board, and only a 404.** `fetch_board` raises `BoardNotFound` and `probe` returns `found=False`. A 404 is never cached, so a board that is created later is found on the next call. A 403, a 410 and a server error propagate and are never read as missing.
- **The description prefers the plain text.** The text is `descriptionPlain` when it has any text, else `descriptionHtml` through `html_to_text`. There is no `html.unescape` step. A plain description that is too long skips the job, since the html form would be at least as long. `publishedAt` is optional, so `posted_at` is `None` when it is missing, and `location` is optional and becomes an empty string.
- **`ASHBY_FETCH_LIMITS` is JSON only, 16 MiB and 60 seconds.** The cap is about eight times the measured 1.95 MB board. A caller must build `PoliteClient` with it. The adapter asks for no compensation data and sends no query string.

## Consequences

- A caller can tell a board that shrank because jobs were unlisted from one that shrank for another reason, because `unlisted` is reported beside `skipped`.
- A probe costs a whole board download, about 2 MB for a board with full descriptions. The cache turns that into a single download for the probe and the fetch together.
- A board whose every job is malformed is still found by `probe`, and `fetch_board` then fails it by the skip budget with a named field. The probe is an existence check, and the fetch is where a board is judged.
- The unlisted path has no live evidence. The tests drop jobs from a copy of the recorded fixture by editing it in test code, and the component and unit tiers drive it against real local servers and hostile hand written boards. The live tier checks the real host, the real shape, the real 404 and the real weak ETag round trip.

## Alternatives considered

- **Probe by status only.** One 200 would be enough to say found. It would let a board that fails every fetch, for example a 200 with an HTML or an error body, be added to the watchlist as if it were healthy. Rejected.
- **Probe by parsing every job.** It would give the strongest answer. It would also hide a real board behind a per job problem, since one malformed job in a good board would make the board look absent. Rejected in favor of checking the shape alone.
- **Count an unlisted job as a skip.** It would reuse the existing field. An unlisted job is correct data, not a fault, and counting it would push a mostly unlisted board over the 10 percent budget. Rejected.
- **Return unlisted jobs as listings in a closed state.** It would keep them visible. The feed says they are not public, and an adapter only ever emits listings in the `new` state. Rejected.
- **Remove the `W/` prefix before sending the tag.** The server accepts the tag as it was given, so altering it would only risk a mismatch. Rejected.

See [the adapter architecture](../architecture.md#board-adapters).
