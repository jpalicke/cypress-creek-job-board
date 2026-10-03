# ADR 0015: Link fetch browser signals

Status: proposed (F2b, pending PR review)

## Decision

`fetch_posting(url)` uses the guarded `fetch_url` transport with fixed limits. It returns bounded raw bytes and provenance or a typed, redacted failure. HTTP 401 is a clear authentication signal and becomes `NeedsBrowser` with guidance to paste the posting text manually. A zero-byte successful response becomes `Empty` with the same guidance. HTTP 403 and other unsuccessful statuses remain `FetchFailed`.

A successful HTML response is returned as bytes even when the page may require JavaScript to display a posting. F2 does not parse HTML or execute scripts. F3 will inspect the content when it implements HTML-to-text extraction and can provide more specific guidance then.

## Why

Response status 401 clearly says authentication is required. Status 403 can mean a policy block, rate control or another denial; a browser is not necessarily a remedy. Raw 200 HTML alone does not establish whether a script-rendered page contains a usable posting. Guessing from a few byte patterns in F2 would duplicate F3's parser and produce misleading errors.

This boundary keeps the one-off fetcher small while preserving the SSRF, redirect, content-type and size checks in the transport. The caller can distinguish failures by exception type without seeing hostile response bodies or URLs in messages.

## Evidence

Real local-server tests cover HTML, plain text, PDF, an empty body, HTTP 401, HTTP 403, redirects, blocked private targets and caps. Public-network tests fetch a job announcement page and a PDF; a separate Python consumer process exercises the production entry and loopback rejection. See [the setup guide](../setup.md), [fetch architecture](../architecture.md) and [threat model](../threat-model.md).
