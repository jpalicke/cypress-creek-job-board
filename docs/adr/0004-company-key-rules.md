# ADR 0004: Company key rules, Unicode confusables data, spaces removed

Status: accepted (Joe P, card B6a)

## Decision
- One function, `company_key`, produces the comparison key for every company name.
- The key is NFKD, casefold, the Unicode confusables skeleton applied until stable, accents and format characters dropped, periods and apostrophes dropped, other punctuation as separators, `i` folded to `l`, trailing legal suffixes stripped, then all words joined without spaces.
- Spaces are removed from the final key so a spacing trick (`Ac me`) cannot dodge a blacklist. The cost is that two genuinely different names that differ only by spacing collide. For a blacklist that fails safe.
- The homoglyph data is the full Unicode `confusables.txt` (UTS #39), bundled unmodified in `config/confusables.txt` and credited in `NOTICE` under the Unicode terms of use. An earlier hand curated Cyrillic and Greek table was replaced by it, which also folds look-alikes such as `0` for `o`, `1` for `l` and `m` for `rn`. Updating means replacing the file.
- `i` is folded to `l` explicitly because casefolding runs first (so names compare case insensitively) and turns the capital `I` into `i` before the table could map it to `l`.
- Legal suffixes live in code (`LEGAL_SUFFIXES`) because each one changes security behavior and needs its own test row. A suffix is only stripped from the end and never when it would leave nothing. They are compared in folded form.
- Idempotence is a tested property: `company_key(company_key(x)) == company_key(x)`. The fold runs a fixed number of passes, and a test checks every character in the data is stable.

## Why
A blacklist is only as strong as its normalizer, so there is one, it is deterministic and it has no network or clock dependency. Dropping spaces and using the full confusables data closes the cheap bypasses (case, spacing, Cyrillic `a`, `Inc Inc`, `lBM`) while keeping the remaining limits (documented in data-model.md) visible.
