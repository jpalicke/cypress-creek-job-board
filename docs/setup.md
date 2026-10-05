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
