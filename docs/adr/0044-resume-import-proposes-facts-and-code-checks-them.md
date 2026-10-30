# ADR 0044: Resume import proposes facts, and code checks them against the resume

Status: accepted (pod decision for card F5, #170; Joe P's review pending)

## Context

Anyone should be able to start a fact bank from a resume, not only someone who can hand write YAML. A resume is hostile input (injection text, hidden PDF text, odd Unicode), and a model that reads it can invent a number, an employer or a skill. The one rule applies in full: a fact may only say what the resume says, and nothing becomes verified except by a person.

## Decision

- **The model proposes, code decides, a person approves.** One model call returns candidates. Deterministic validator V15 keeps only those whose claim is supported by their own source span. Approving a candidate (a later, separate step) writes an unverified, local only fact; verification stays the explicit per fact button of the fact bank screen.
- **A candidate carries only a claim, a kind, tag names and its exact source span.** There is no field for a level, dates, an employer, an id or a verification. A level of skill and a date range are judgements the resume rarely states exactly, so a person adds them when reviewing. The schema forbids extra fields, so a reply that tries to carry one is a schema failure for the whole answer.
- **V15 is strict and cheap.** The span must be a continuous, exact piece of the normalized resume. Every number, quantity word, month, capitalised word (including the first word) and tag of the claim must be in the span. Tags may be matched through the alias table. A proposal that fails is dropped and counted by reason, without its text, and never repaired. The strictness means a paraphrase that changes a capitalised word is dropped; the prompt asks the model to reuse the resume's words.
- **"Closed tag vocabulary" means grounded tags.** The repository has no closed list of skill names (the alias table has a dozen canonical entries), so a tag is accepted only if it, or an alias, appears in the span. Tag names are normalized with the same function as the bank. Imported tags get the lowest level when approved.
- **Duplicates are merged and the bank is never overwritten.** Claims are compared with case, spaces and edge punctuation folded. A claim already in the bank is not proposed again.
- **Privacy.** The resume is normalized, sent to the chosen backend and forgotten: only a hash is stored. A hosted backend needs `confirm_hosted`, as for analysis, because the resume is personal data. Pasted text and PDFs (through the limited PDF extractor, so hidden PDF text never reaches the model) are the only inputs.

## Consequences

- A good, faithfully worded candidate list is the expected result; a creative model gets many proposals dropped, which is the safe failure.
- Lower case words are not checked by V15, so a wrong verb or tool in lower case can pass if its capitalised and numeric parts are grounded. A person reads every candidate.

## Alternatives considered

- Let the model set levels and dates: rejected, an invented level is the easiest false claim to make and the hardest to see.
- Repair a near miss (fix a number from the span): rejected, a repair is a new claim made by code.
- Store the resume to allow re-checking later: rejected, personal data kept for no need.
