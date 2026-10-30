# ADR 0043: PDF text comes from pypdf in a limited child process

Status: accepted (library approved by Joe P: "pypdf is fine"; pod design, his review pending). Replaces the typed 501 `pdf_extraction_unavailable` of [ADR 0030](0030-posting-and-analyze-routes.md).

## Context

A PDF parser reading a hostile file is the most dangerous code in the repository. It can hang, exhaust memory, crash, or hand the model text a person never sees. The license must allow MIT distribution, so AGPL libraries (PyMuPDF) are out.

## Decision

- **Library: pypdf 6.21.4.** BSD-3-Clause (the license check passes), pure Python, no native code, and it has built in decompression limits. `pip-audit` on the locked dependencies reports no known vulnerability. pdfminer.six was the alternative; pypdf exposes the content stream operators and text matrices needed to judge hidden text.
- **A child process per file.** The parent checks the size and the `%PDF-` marker, then runs `python -I -m cypress_creek.ingest.pdf_worker` with an empty environment (no secrets), an empty working directory and its own session, sends the bytes on stdin and reads one JSON line. The worker sets its limits before it imports pypdf: address space (default 1 GiB), CPU seconds, no file writes. It also makes sockets unusable. This is defense in depth, not a sandbox, and the threat model says so.
- **Typed errors, never silent truncation.** `PdfTooLarge`, `PdfTooManyPages`, `PdfTooMuchText`, `PdfEncrypted`, `PdfCorrupt`, `PdfNoText`, `PdfTimeout`, `PdfResourceLimit`. Every cap is configurable (`PdfLimits`) with a safe default. A worker that crashes or is killed, or answers too much, is `PdfResourceLimit`. A timeout kills the child.
- **Hidden text is dropped and counted.** The worker walks the page with pypdf's text visitor and the content stream operators. It tracks the fill color (`g`, `rg`, `k`, `sc`, `scn`, with `q` and `Q`), and drops a fragment whose fill is near white (or CMYK with no ink), whose effective font size is under 4 points, or whose origin is outside the page box. Annotations, form fields and document metadata are never part of the text and are counted as warnings. Only visible page text is returned, with `extractor = pypdf <version>`.
- **No OCR and no password attempts.** An image only PDF is `PdfNoText` and the user is told to paste the text. An encrypted file is refused without trying a password.
- **Routes.** `POST /api/postings` with a PDF body, and a link that returns a PDF, now go through the extractor. The typed errors map to 4xx codes (`pdf_corrupt` and the others in docs/api.md). The warnings appear as `extraction_warnings`.

## Consequences

- Hidden text is judged from the content stream only: white text on a colored background, text under an image and clip paths are not detected. The threat model lists these limits.
- POSIX resource limits do not exist on Windows. There the timeout and the decoded size cap apply but the memory limit does not; the worker self check reports `limits_applied`.
- Each PDF costs one process start (about 0.3 s). That is acceptable for a user initiated upload.

## Alternatives considered

- Parsing in the server process: rejected, a hang or a crash would take the API down.
- pdfminer.six: a fine library, but pypdf's operator visitor and decompression limits fit the hidden text rules with less code.
- A container or seccomp sandbox: stronger, but not portable to a contributor's machine from a clone. Recorded as a possible hardening.
