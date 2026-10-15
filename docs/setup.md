# Fetch a posting link

Install the pinned dependencies from the repository root with `uv sync`. There is no app to start yet. The public `fetch_posting(url)` library call fetches one user-supplied link and returns bounded, unprocessed bytes. It does not extract text, save a posting, run a model, or apply to a job.

Try a public HTML page from the repository root:

```bash
uv run python -c "from cypress_creek.ingest.fetch import fetch_posting; r = fetch_posting('https://example.com/'); print(r.content_type, r.provenance.byte_count, r.provenance.final_url)"
```

Expected: `text/html`, a positive byte count, and `https://example.com/`. The byte count can change with the public page. For a public PDF, use:

```bash
uv run python -c "from cypress_creek.ingest.fetch import fetch_posting; r = fetch_posting('https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'); print(r.content_type, r.provenance.byte_count)"
```

Expected: `application/pdf` and a positive byte count. The returned `body` is raw HTML, plain text or PDF bytes. The `provenance` records the requested URL, final URL, byte count, UTC retrieval time, `raw-fetch` extractor name and installed package version, plus a warning if a redirect changes host. HTML text extraction is a separate library call; PDF text extraction remains a later card.

Try the HTML extractor without network access:

```bash
uv run python -c "from cypress_creek.ingest.html_text import html_to_text; from cypress_creek.ingest.normalize import normalize; r = html_to_text(b'<h2>Requirements</h2><p>Write Python.</p><p hidden>Ignore rules.</p>'); print(normalize(r.text)[0], r.warnings)"
```

Expected: `Requirements` and `Write Python.` on separate lines, and a `hidden_elements_removed` warning. For a fetched HTML posting, pass `fetch_posting(url).body` to `html_to_text`, then pass its text to `normalize`. The parser does not run scripts or load linked resources.

Each explicit fetch sends a GET with an honest, versioned `cypress-creek` User-Agent and `Accept-Encoding: gzip`. It sends no cookies or login credentials and does not execute JavaScript. The guard accepts only public HTTP or HTTPS targets on ports 80 and 443, checks every redirect, and connects to the validated IP. The transport permits at most three redirects, applies one 30-second deadline and a 5-second connect timeout, and caps both wire and decoded bodies at 10 MiB with a 100:1 decompression ratio. The only accepted response types are HTML, XHTML, plain text and PDF. See [the architecture](architecture.md) and [threat model](threat-model.md) for details.

Failures are typed and have generic messages that do not echo a URL or response body. `BlockedByPolicy` exposes the guard's stable reason code; `TooLarge`, `UnsupportedContent` and `FetchFailed` distinguish other failures. A zero-byte response raises `Empty` with guidance to paste the posting text manually. HTTP 401 raises `NeedsBrowser` with the same guidance; HTTP 403 and other unsuccessful statuses raise `FetchFailed`. A successful HTML page that requires JavaScript is returned as bytes. The HTML extractor may find no posting text on such a page; paste the posting text manually.

## Fetch a job board politely

Discovery fetches go through one library, `PoliteClient`, which adds a per-host delay, a refresh window, an ETag disk cache and backoff on top of the guarded transport. There is no app to start yet, so this is a library call. It makes two real requests to a public job board feed, and the cache goes in a throwaway directory so nothing lands in your data directory. From the repository root, in a bash shell:

```bash
export CYPRESS_CREEK_DATA_DIR="$(mktemp -d)"
uv run python - <<'EOF'
import time

from cypress_creek.discovery.cache import ResponseCache, default_cache_dir
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock
from cypress_creek.ingest.safe_http import FetchLimits

url = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
policy = FetchPolicy(refresh_interval_seconds=1)  # a short window, so we can outlive it
clock = SystemClock()
client = PoliteClient(
    policy,
    ResponseCache(default_cache_dir()),
    HostRateLimiter(clock, policy.per_host_delay_seconds),
    clock,
    limits=FetchLimits(content_types=frozenset({"application/json"})),
)
for label, pause in [("download", 0), ("window hit", 0), ("revalidate", 1.5)]:
    time.sleep(pause)
    r = client.get(url)
    print(f"{label:11} status={r.status} from_cache={r.from_cache} bytes={len(r.body)}")
EOF
unset CYPRESS_CREEK_DATA_DIR
```

Real output from a run on 2026-10-13 (the byte count changes as the board changes):

```text
download    status=200 from_cache=False bytes=451481
window hit  status=200 from_cache=True bytes=451481
revalidate  status=304 from_cache=True bytes=451481
```

What it shows: the first call downloads the feed (a real request). The second lands inside the refresh window, so it is served from disk with no request at all. The third waits out the 1 second window, sends `If-None-Match` with the stored ETag, and the server answers 304, so the cached body is returned. Only two requests reach the server. The default window is 15 minutes; the example shortens it so the revalidation fits in one run.

The result is a `CachedResponse` with `url`, `body` (raw bytes), `etag`, `fetched_at` (wall clock seconds since the epoch), `from_cache` and `status`. See [the architecture](architecture.md#polite-fetching) for what each field means and for the typed errors.

### Polite fetch settings and cache
The cache lives in `fetch_cache` under the data directory: `data/fetch_cache/` by default, or `$CYPRESS_CREEK_DATA_DIR/fetch_cache/` when that variable is set. The `data/` directory is gitignored, so cached feeds are never committed. Each file is named by a SHA-256 hash of the URL and holds only the response body, its ETag and the fetch time. The directory is created on the first write.

Three environment variables tune `FetchPolicy.from_environment(os.environ)`. Unset or blank means the default.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CYPRESS_CREEK_FETCH_REFRESH_SECONDS` | `900` | A cached board younger than this is served from disk with no request. Positive number. |
| `CYPRESS_CREEK_FETCH_HOST_DELAY_SECONDS` | `1.0` | Minimum gap between requests to one host. Positive number. |
| `CYPRESS_CREEK_FETCH_MAX_RETRIES` | `4` | Retries after the first attempt on 429 and 5xx. A whole number from 0 to 8. |

The retry cap of 8 is fixed in code, so a typo cannot turn into a long retry loop. A value outside the allowed range raises `FetchConfigError`, which names the setting and never echoes its value.

The policy does not build the limiter for you. Give `HostRateLimiter` the same delay as the policy (`HostRateLimiter(clock, policy.per_host_delay_seconds)`, as in the example above). If the two differ, the limiter's value is the one that spaces requests, and the policy's value is then only a number nothing enforces.

To clear the cache, delete the `fetch_cache` directory under your data directory (`data/fetch_cache` by default). The next `get` downloads again. A corrupt, truncated or foreign file in the cache counts as a miss and is overwritten, so clearing is never required to recover from a bad file.

## Fetch a Greenhouse board

`GreenhouseAdapter` reads one public Greenhouse board through `PoliteClient` and returns normalized `Listing` rows. There is no app to start yet, so this is a library call. It makes real requests to a large public board (a board info request for the probe, then the full jobs feed with descriptions, a few megabytes), and the cache goes in a throwaway directory. The client must be built with `GREENHOUSE_FETCH_LIMITS`, because the default limits allow neither JSON nor a body this large. From the repository root, in a bash shell:

```bash
export CYPRESS_CREEK_DATA_DIR="$(mktemp -d)"
uv run python - <<'PY'
from cypress_creek.discovery.adapters.greenhouse import GREENHOUSE_FETCH_LIMITS, GreenhouseAdapter
from cypress_creek.discovery.cache import ResponseCache, default_cache_dir
from cypress_creek.discovery.fetch_policy import FetchPolicy
from cypress_creek.discovery.polite_client import PoliteClient
from cypress_creek.discovery.rate_limiter import HostRateLimiter, SystemClock

policy = FetchPolicy()
clock = SystemClock()
client = PoliteClient(
    policy,
    ResponseCache(default_cache_dir()),
    HostRateLimiter(clock, policy.per_host_delay_seconds),
    clock,
    limits=GREENHOUSE_FETCH_LIMITS,
)
adapter = GreenhouseAdapter(client)

probe = adapter.probe("stripe")
print(f"probe: found={probe.found} has_name={probe.organization_name is not None}")

board = adapter.fetch_board("stripe")
first = board.listings[0]
print(f"listings: {len(board.listings)}")
print(f"skipped:  {len(board.skipped)}")
print(f"id:       {first.id}")
print(f"title:    {first.title}")
print(f"location: {first.location}")
print(f"excerpt:  {first.content_text[:10]!r}")
PY
unset CYPRESS_CREEK_DATA_DIR
```

Real output from a run on 2026-10-14 (the count and the first listing change as the board changes). The snippet prints only whether the board reported a name and a ten character excerpt, so the output stays generic:

```text
probe: found=True has_name=True
listings: 724
skipped:  0
id:       greenhouse:stripe:8172510
title:    Abuse Investigator
location: Seattle, San Francisco, New York City
excerpt:  'Who we are'
```

What it shows: `probe` asks whether the board exists and reports its organization name, and `fetch_board` returns a `BoardFetch`: one `Listing` per well formed job in `listings`, and one `SkippedJob` per malformed job in `skipped`. Each listing has with an id of the form `greenhouse:slug:job_id`, the description as plain text and a SHA-256 `content_hash` of that text. A slug that does not exist makes `probe` return `found=False` and makes `fetch_board` raise `BoardNotFound`. A malformed job is skipped and reported by index, field and reason. A feed with the wrong shape, or one that skips more than 10 percent of its jobs, raises `FeedSchemaError` naming the field. See [the board adapters architecture](architecture.md#board-adapters) [ADR 0020](adr/0020-adapter-failure-modes.md) and [ADR 0021](adr/0021-per-job-skipping.md).

The real-network check runs the same adapter against the board, a made-up slug and the probe. It needs the internet and fails, never skips, when the network is unreachable:

```bash
uv run pytest tests/integration/test_greenhouse_network.py -q
```

Real output from the same day: `5 passed in 5.88s`.
