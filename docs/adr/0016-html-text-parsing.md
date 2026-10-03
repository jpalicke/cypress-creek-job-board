# ADR 0016: Bounded HTML text parsing

Status: proposed (F3)

## Decision

Parse fetched HTML with Python's standard-library `html.parser.HTMLParser`. Decode a bounded byte input using a UTF-8 BOM, a valid caller hint, an early meta charset, or UTF-8 with replacement as the fallback. Reject inputs above 10 MiB or nesting above 128 elements with typed errors. Do not execute JavaScript or load external resources.

Keep headings and list items on separate lines. Exclude scripts, styles, templates, comments, metadata and elements hidden by supported attributes or inline CSS. Count hidden elements in a warning. Keep uncertain content rather than risk losing a requirement.

## Why

The standard-library parser has no resource fetching or script execution. It does not introduce a third-party dependency or license into the runtime. A stack of element frames keeps hidden descendants suppressed even when tags are nested or malformed. Bounded input and nesting limit parser work and memory use. The parser does not implement a browser's CSS layout; external stylesheets and JavaScript-rendered content remain visible limits.

## Evidence

Unit tests cover hidden techniques, line structure, entity decoding, encoding fallback, size and depth errors, and arbitrary byte input. Component tests over saved public posting pages and hostile pages are part of the same card.
