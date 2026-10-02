# ADR 0002: Posting whitespace and normalization order

Status: proposed (card B3, for Joe P to confirm in the PR)

## Decision
- Runs of spaces and tabs collapse to one space, and trailing spaces on a line are dropped.
- Single newlines are kept, and runs of blank lines collapse to one blank line. Later stages (the cue sentence scan and heading cues) need the line structure.
- `\r\n`, `\r`, U+2028 and U+2029 all become `\n`.
- Control and format characters (categories Cc and Cf, which include zero-width and bidi marks) are stripped and counted in a `control_chars_stripped` warning. Newline and tab are not counted.
- Order: line endings, strip, NFKC, whitespace, trim. Stripping happens before NFKC so a stripped character can never leave two pieces that NFKC would then compose, which keeps `normalize` idempotent.
- The 30,000 character cap applies to the normalized text. Raw input over 300,000 characters is refused up front so hostile input cannot force unbounded work. Both raise `PostingTooLong`. Text is never cut.

## Why
Spans and cue scans must all refer to one text, so the cleanup rules have to be fixed and repeatable. Keeping single newlines costs nothing and preserves headings and bullet structure.
