# ADR 0025: Dedupe merges only exact fingerprints across sources, filters count their first rejection, and only a clean successful fetch closes a listing

Status: accepted (card H6). Builds on [ADR 0021](0021-per-job-skipping.md).

## Context

Discovery must cut the listings down before any model call, without hiding a real posting. A listing carries no company name, only a board, and the adapters report malformed jobs as skipped instead of failing the board.

## Decision

- **A fingerprint merge needs different sources and an exact match.** Listings merge across `ats` only when company key, title and location fingerprints are equal. Within one source, equal fingerprints are separate jobs. If a fingerprint group holds the same source twice, nothing in the group merges, because the pairing is ambiguous.
- **The fingerprint keeps `#`, and `+` is never stripped.** Dropping all punctuation would make `C++ Engineer` and `C Engineer` equal. A false merge is worse than a visible duplicate, so a mark that changes meaning is kept. Other punctuation becomes a space.
- **The company key comes from the caller.** `dedupe` takes a map from normalized `(ats, slug)` to company key (from the watchlist), instead of guessing a company from a slug. A board with no key is never merged across sources.
- **Same id, many copies: the latest fetch wins, with a total order.** The tie breaker covers every field, so the result is independent of input order. The merged listing keeps the smallest id, the earliest `posted_at` and all URLs.
- **A listing with no date passes the age filter.** Age cannot be judged, and hiding it would be the worse error.
- **Each removal is counted under the first filter that rejects it,** in a fixed order, so the counts sum to the total removed.
- **A closed listing that returns is `seen`, not `new`.** It has been stored before. Whether the user has acted on it is not tracked here.
- **Only a whole, clean fetch closes.** `apply_fetch` is reached only after `fetch_board` returned, so a failed fetch writes nothing. A skipped job with a known id protects its listing. A skipped job with no id stops closing for that fetch. An empty successful fetch does close the board, because `[]` is a valid board.

## Consequences

- A cross-source duplicate whose titles differ by even one word is shown twice. That is accepted.
- A board that skips jobs without ids never closes anything until it fetches clean. Stale listings last longer, and none is closed wrongly.
- The company map must be built from the watchlist by the scan card H8 (#47), which is the first caller of all of this.

## Alternatives considered

- **Fuzzy title matching.** Rejected: near matches stay separate by rule.
- **Merge when one source repeats, keeping the best pair.** Rejected: any pairing rule is a guess.
- **Close on any successful fetch regardless of skips.** Rejected: a malformed job would look closed (the silent shrink ADR 0020 and 0021 exist to prevent).
