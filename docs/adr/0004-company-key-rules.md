# ADR 0004: Company key rules, curated homoglyph table, spaces removed

Status: accepted (Joe P, card B6a)

## Decision
- One function, `company_key`, produces the comparison key for every company name.
- The key is NFKD, accents and format characters dropped, casefolded, homoglyphs folded, periods and apostrophes dropped, other punctuation as separators, trailing legal suffixes stripped, then all words joined without spaces.
- Spaces are removed from the final key so a spacing trick (`Ac me`) cannot dodge a blacklist. The cost is that two genuinely different names that differ only by spacing collide. For a blacklist that fails safe.
- The homoglyph table is hand curated (Cyrillic and Greek) in `config/confusables.yaml`, not generated from the Unicode confusables data. It avoids a download and a license note, is easy to review, and is extended with a test whenever a new lookalike appears. Swapping in the full Unicode data later only changes that file and its loader.
- Legal suffixes live in code (`LEGAL_SUFFIXES`) because each one changes security behavior and needs its own test row. A suffix is only stripped from the end and never when it would leave nothing.
- Idempotence is a tested property: `company_key(company_key(x)) == company_key(x)`.

## Why
A blacklist is only as strong as its normalizer, so there is one, it is deterministic and it has no network or clock dependency. Dropping spaces and folding lookalikes closes the cheap bypasses (case, spacing, Cyrillic `a`, `Inc Inc`) while the documented limits (ASCII lookalikes such as `rn` versus `m`) stay visible rather than being papered over.
