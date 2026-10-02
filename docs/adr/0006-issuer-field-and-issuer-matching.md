# ADR 0006: Issuer field on facts and requirements, matched with company_key

Status: accepted (Joe P, card #57)

## Decision
- `Fact` gains an optional `issuer` for the school or certifying body of an education or certification fact. `employer` keeps its meaning for employment and projects.
- `Requirement` gains an optional `issuer`, filled by extraction when the posting names one.
- Both are trimmed and must hold a letter or digit, checked by one function, `clean_issuer`.
- The support gate compares issuers with `company_key`, the one organization name normalizer, so case, spacing, legal suffix and lookalike variants match.
- An education or certification requirement that names an issuer is met only by a fact with the same issuer. A fact with no issuer is not a candidate. A requirement without an issuer behaves as before. An issuer on any other requirement kind is ignored.
- Validators V7, V8 and V10 do not read `issuer` yet. That follows in a separate card so each change stays small.

## Why
Before this, a requirement for a degree or certificate from a named issuer was met by any fact of that kind with the right tag, which overstates support. Storing the issuer in `employer` would label a school as an employer and confuse V7. Renaming `employer` would break existing banks. An optional new field is the smallest honest change. Reusing `company_key` keeps one normalizer for organization names.
