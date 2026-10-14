# ADR 0019: Polite fetch timing, clocks and pass-through statuses

Status: accepted (Joe P, card H2)

## Context

The polite fetch layer must keep requests to one host at least one second apart, honor a refresh window, revalidate with ETags and back off on 429 and 5xx. Three design questions came up while building it, each settled by a failing test or a gap in the transport.

1. Where does the one second gap start? The first component test asked two requests to one real local server to be at least 1 second apart, measured by the server's own timestamps. The first limiter recorded the time just before each request began. The test failed with a server-side gap of 0.946 seconds. The request goes through a disposable worker process, and worker startup time varies between runs, so the moment the limiter stamped and the moment the request actually reached the server differed by tens of milliseconds, in the wrong direction.
2. Which clock ages a cache entry? The limiter needs a clock that never goes backwards. A cache entry outlives the process, so its stored time must mean the same thing after a restart.
3. How does the client see 304, 429 and 5xx? The guarded transport raised `SafeHttpError` for every non-2xx status and discarded the headers, so the client could neither read a `Retry-After` nor distinguish a 304 from a failure.

## Decision

- The delay is measured from the end of the previous request. `HostRateLimiter.wait(host)` sleeps until the delay has passed since the last stamp, and `HostRateLimiter.finished(host)` restamps the host when a request ends. `PoliteClient` calls `finished` in a `finally` block after every attempt, successful or not. The gap the server sees is therefore never shorter than the delay, however long the worker took to start, and a slow response only lengthens the gap.
- Time comes from an injected `Clock` with two readings. `monotonic()` drives the limiter, because it cannot jump. `time()` (wall clock seconds since the epoch, added to the `Clock` protocol for this) stamps and ages cache entries, because a monotonic reading means nothing after a restart. A cache entry is fresh when `0 <= now - fetched_at < refresh_interval`. A stamp in the future (the wall clock moved back) is stale, so the client revalidates rather than trusting it. `SystemClock` is real time. `ManualClock` moves both readings together only when told to, so tests control time without sleeping. It is time, not a mocked collaborator.
- The transport gains an opt-in flag. `fetch_url(..., pass_through_statuses=True)` returns an empty-body `FetchResponse` for 304, 429 and 5xx, with the status and the cleaned `etag` and `retry_after` header values, instead of raising. It also accepts `if_none_match`, validated as printable ASCII, 512 characters at most. The default is `False`, so `fetch_posting` and every other caller keep the old behavior: any non-2xx still raises. Other statuses still raise `SafeHttpError` even with the flag, and 401 keeps its dedicated reason. The flag never relaxes the URL guard, the byte caps or the content type check for a 2xx body.

## Consequences

- The one second spacing is a floor on the observed gap, not an average. The cost is that the effective request rate is slightly below one per second when responses are slow, which is the polite direction.
- `HostRateLimiter` holds one lock, so a sleeping caller also holds back callers for other hosts. This is acceptable for a serial, single user tool and keeps the limiter simple. A concurrent scheduler would need a lock per host.
- The limiter's delay and `FetchPolicy.per_host_delay_seconds` are separate values that the caller must keep equal ([setup](../setup.md#polite-fetch-settings-and-cache)). A single wiring helper may remove that step in a later card.
- Cache freshness depends on the wall clock. A clock set far into the past makes entries look like they are from the future and forces revalidation, which is safe. A clock set far into the future ages entries early, which costs one extra revalidation request.
- Any future caller that needs the status of a non-2xx response opts in explicitly with the flag. Code that does not opt in cannot receive an error body by accident, which keeps the rule that failures carry no remote text.
- Tests drive the real transport against real local servers. The 0.946 second finding stays covered by the component test that compares server-side timestamps.

See [the fetching architecture](../architecture.md#polite-fetching), [ADR 0013](0013-pinned-http-transport.md) and [setup](../setup.md#fetch-a-job-board-politely).
