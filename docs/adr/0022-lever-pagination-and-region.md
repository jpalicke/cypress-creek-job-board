# ADR 0022: Lever reads a board page by page, fails a board that fills the page cap, and finds its host by asking US then EU

Status: accepted (Joe P, card H4). Builds on [ADR 0020](0020-adapter-failure-modes.md) and [ADR 0021](0021-per-job-skipping.md), which still apply to Lever.

## Context

The Lever postings feed differs from the Greenhouse feed in four ways that shape the adapter. It is paged: `GET /v0/postings/{slug}?mode=json&limit=N&skip=M` returns a bare JSON array of at most `N` postings, and a page past the end is `[]`. A board is served from one of two hosts, `api.lever.co` for US accounts and `api.eu.lever.co` for EU accounts, and the US host answers 404 for an EU board. The feed carries no company name, so the slug is the only identity. And the description is real HTML, split across `description`, a `lists` array of headed sections, and `additional`, not one escaped string.

These were checked live on 2026-10-14. A missing slug is HTTP 404 with a JSON body. One board had 314 postings, and a single page of 100 postings with full descriptions measured 1.9 MB.

## Decision

- **Paging stops on a short page.** `LeverAdapter` requests pages of `page_size` postings (default 100, the most Lever allows, accepted from 1 to 100) with `skip` advancing by one page. A page with fewer postings than `page_size` is the last page. A board whose size is an exact multiple of the page size ends on an empty page, which costs one extra request.
- **A board still full at the page cap fails whole.** `MAX_PAGES` is 50, which is 5000 postings at the largest page size. If the fiftieth page is still full, `fetch_board` raises `FeedSchemaError` for the `jobs` field. It never returns the first 5000 postings as if they were the board. A truncated board would make every posting past the cap look closed later, which is the silent shrink that ADR 0020 and ADR 0021 exist to prevent. The cap also bounds the work a hostile or broken feed can cause, such as a server that repeats a full page forever.
- **A repeated posting keeps its first copy.** The list can shift between page requests, so one posting may arrive on two pages. Postings are deduplicated by their own `id`, the first copy wins, and a posting without a plain id is left for the mapper to skip. Nothing is dropped without a record.
- **The skip budget and the skip index cover the whole board.** All pages are gathered first and then mapped once, so `check_skip_budget` sees the 10 percent figure over the whole board, and a `SkippedJob.index` is the position among the postings kept, not within a page. Bad postings spread across pages cannot each hide under a per page budget.
- **The host is found by asking US, then EU, serially.** With no known region, the first page is requested from the US host. Only a 404 moves on to the EU host. Any other refusal (403, 410, a server error after retries) propagates and is never read as "try the other host". The requests are serial, never parallel, so the per host spacing and the polite policy hold, and a board that exists on the US host never causes an EU request. A 404 from both hosts is a missing board.
- **The region is remembered in memory only.** `region_of(slug)` returns the host a board was last found on, or `None`. A later `fetch_board` of a known board asks only that host. A 404 from the remembered host forgets the region and reports the board missing, so a board that moved is found again by a fresh `probe` or `fetch_board`. A 404 on a later page of a known board also raises `BoardNotFound` and does not fall back to the other host. The adapter keeps no state on disk.
- **`probe` asks for one posting.** It requests `limit=1` from the US host and then the EU host, and returns `ExistenceResult(found=True, organization_name=None)` when either answers. A board with zero open postings answers 200 with `[]` and is found. Only a 404 from both hosts is `found=False`.
- **There is no company name.** `organization_name` is always `None` for Lever, and the slug is the identity. In the discovery design that is weak identity evidence, as the spec already says for Lever and Ashby.
- **The description is converted part by part.** The text is `description`, then for each `lists` entry its heading as one plain line and its content, then `additional`. Each part goes through `html_to_text` on its own and the parts are joined with blank lines, so the end of one part never runs into the start of the next. There is no `html.unescape` step, because the Lever description is real HTML and not escaped HTML. `createdAt` is epoch milliseconds and becomes a timezone aware `posted_at`; a value that is not a representable time skips the posting.
- **`LEVER_FETCH_LIMITS` is JSON only, 16 MiB and 60 seconds.** The cap is about eight times the measured 1.9 MB page. A caller must build `PoliteClient` with it. The default limits allow neither JSON nor a body this large.
- **The shared helpers moved out of the Greenhouse module.** `FeedModel`, `field_path` and `plain_line` live in `discovery/adapters/feed_common.py`, and both adapters import them. There is one definition of the strict feed model and of the plain line rule.

## Consequences

- A large board is read in a handful of requests, one second apart, and every page goes through the same cache and politeness policy as any other feed. A board of 314 postings is four pages at the default page size.
- A board of more than 5000 postings cannot be read until `MAX_PAGES` is raised. That is a loud failure with a one line fix and a test that names the value, not a quiet loss.
- Whoever calls `fetch_board` for a board never has to know the host. A caller that needs to know it (to store it, for example) reads `region_of` after a successful `probe` or fetch.
- A fresh process knows no regions, so its first fetch of an EU board makes one extra request to the US host that answers 404. A 404 is never cached, so that request is repeated on every fresh process. This cost is accepted for now. Persisting the region on the watchlist entry belongs to the discovery tables and the scan, cards H1 (#40) and H8 (#47), and a follow up issue will track it.
- Live findings, recorded honestly. On 2026-10-14 a public board had 314 postings across about 32 pages at page size 10 and none were skipped. The only EU board found was `kaiko`, which had no open postings that day, so the EU live test asserts the probe, the region and a clean fetch but not a posting count. Forty other candidate EU slugs were tried and all answered 404, so no EU board with open postings was available to record.
- The skip, dedupe, cap and host fallback behavior is covered by component tests that drive the adapter against real local HTTP servers, and by unit tests on hand written hostile feeds, because a healthy public board exercises none of them. The live tier checks the real hosts, the real paging and the real descriptions.

## Alternatives considered

- **Persist the region now.** A `region` column on the watchlist would avoid the extra US request for EU boards. It changes the watchlist schema and its migration, which belongs to H1 and H8, and it would make an adapter card edit the discovery tables. Deferred, with the in-memory `region_of` as the seam.
- **Put the region on `ExistenceResult`.** It would carry the region from `probe` to the caller with no adapter state. But `ExistenceResult` is the shared contract for every adapter, and only Lever has regions. Adding a field there changes Greenhouse and every later adapter for one vendor's detail.
- **Probe both hosts in parallel.** It would find an EU board one round trip sooner. It breaks the one request at a time rule of the politeness policy and sends an EU request for every US board, so it was rejected.
- **Truncate at the page cap.** Returning the first 5000 postings would be simpler for the caller, and it is exactly the silent shrink the skip budget exists to stop. Rejected in favor of failing the whole board.

See [the adapter architecture](../architecture.md#board-adapters).
