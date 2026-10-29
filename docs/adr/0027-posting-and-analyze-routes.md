# ADR 0027: The posting and analyze routes: lazy storage, a budget per request, PDF held back and verdicts without offending text

Status: accepted (card G2). Builds on [ADR 0026](0026-api-security-layer.md).

## Context

G2 ties the library to the API. The routes should stay thin, and the rules of lane G still hold: typed errors only, no keys or remote content in an answer, a hosted backend never the silent default.

## Decision

- **A down backend is a 200 with an incomplete report.** `analyze` already fails closed into an incomplete report with no score and a reason, so the route returns it and stores it. A `BudgetExceeded` and a refused report (`ReportRefused`) are the two failures that are real errors, as typed 409 and 422 answers.
- **The route stores every report as its own row.** A rerun of the same inputs can differ, so the report id is random (`rep-` and 16 hex characters) and the pipeline's `run_id` stays inside the report as provenance.
- **Verdicts are stored and returned without `offending`.** The verdict text can hold posting or model text, and an answer must not carry raw remote content. The validator id, stage, subject, result and reason are enough to see why a report was accepted.
- **PDF upload is checked and then held back.** The size cap and the `%PDF-` check exist now, before anything reads the body. PDF text extraction belongs to card F4, which waits on the hostile fixtures of E6, so a plausible PDF gets `pdf_extraction_unavailable` (501). A link that returns a PDF gets the same answer. The route will call F4 when it exists.
- **Body size is limited by declared length, before the body is read.** A chunked body is refused (411), a JSON body over 1 MiB and a PDF over 10 MiB are refused (413). The server reads exactly the declared length, so the declared length is the limit. This is an ASGI middleware, so every later route inherits it.
- **The budget is per request.** Each analysis builds a tracker from the provider settings and wraps the provider in `BudgetedProvider`. Nothing is saved across requests, so a long session can spend more than one request's budget. A run level budget needs a spend ledger, which is a later card. The estimate route uses the same budget and `dry_run_estimate`. It covers the extraction call only, because the number of entailment calls depends on what the model extracts.
- **A hosted backend must be named and confirmed.** The request names the configured provider, a hosted one also needs `confirm_hosted: true`, and the check is a pure function that is tested without any hosted adapter.
- **The database is created on first use.** Building the app touches no disk, so tests and tools that build it leave no file behind. The server prepares it at startup so a bad database fails fast. The bank file is read on every request, so an edit takes effect at once.
- **Facts validation is a data answer.** `POST /api/facts/validate` always answers 200 with `valid` and a short `problem`, because a user checking a file wants to see the problem, not an HTTP error. The first line of a loader message is kept at most 200 characters, and the YAML is never echoed.
- **Each posting submission is a new row.** The posting id is random, so the same text pasted twice makes two postings. The `text_hash` shows they match.

## Consequences

- The UI can show a clear reason for each failure from the `code`, and can offer "paste the text instead" for fetch problems.
- A saved database from an older build gets the new tables when the app first uses it.
- Until F4 lands, PDFs cannot be ingested through the API.

## Alternatives considered

- Deduplicate postings by `text_hash`. Rejected: the origin and time differ, and a stored report belongs to one submission.
- Return the validator verdicts with their offending text. Rejected for the reason above.
- A multipart upload for the PDF. Rejected: it needs a new dependency, and a raw body with a content type is enough for one file.
