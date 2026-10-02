# Validators

The validators are the control that makes the grounding promise true even if the model is hostile. Every model output is attacker-controlled data, and these pure functions (no model, no network, no clock) decide whether it may be used. The eval harness runs the same functions, so production and evals cannot disagree about what "grounded" means.

All of them live in `src/cypress_creek/validators/`. Each returns a `Verdict` (`validator`, `passed`, `reason`, `offending`). `REGISTRY` in `validators/registry.py` lists every validator by id so a harness can look one up and run it.

## Catalogue
| Id | Name | Rejects | Module |
| --- | --- | --- | --- |
| V1 | Schema | Malformed or extra-field output | `extraction.py` |
| V2 | Verbatim span | Invented or altered requirements | `extraction.py` |
| V3 | Importance cues | A model promoting or demoting a requirement | `extraction.py` |
| V4 | Fact exists | Fabricated fact IDs | `citations.py` |
| V5 | Fact verified | Citing unverified facts | `citations.py` |
| V6 | Fact shareable | Privacy leaks to a hosted backend | `citations.py` |
| V7 | Entity consistency | A real date, employer or role attached to the wrong claim | `consistency.py` |
| V8 | Numeric consistency | Inflated or invented numbers | `consistency.py` |
| V9 | Citation required | Claims with no cited fact | `claims.py` |
| V10 | Novel term flag | Tools, names or acronyms no cited fact mentions (heuristic) | `claims.py` |

More are added as they land (V11 to V14 are in the same card).

## V1 Schema
`check_schema(model, data)`. `data` is JSON text or a mapping. JSON text is validated in strict mode, so wrong types are rejected rather than coerced. Models forbid extra fields, so a smuggled field fails. The verdict names the first offending field.

## V2 Verbatim span
`check_verbatim_span(posting_text, requirement)`. Passes only if `posting_text[start:end] == requirement.text`. Offsets are Python string indexes (Unicode code points) into the normalized posting text, so a lookalike character fails. A span running past the end fails.

## V3 Importance cues
`check_importance(posting_text, requirement)`. The expected importance comes from `cue_importance` in `validators/cues.py`, and the requirement must match it:
1. Cue words in the sentence(s) holding the span decide. Required cues: required, must, must have, mandatory, essential, minimum. Preferred cues: preferred, nice to have, a plus, bonus, desirable, ideally. A sentence with both kinds is ambiguous and gives `unspecified`.
2. With no cue in the sentence, the nearest heading above decides ("Requirements:" gives required, "Nice to have:" gives preferred, any other short heading such as "Benefits:" resets to unspecified).
3. Otherwise `unspecified`. A model that says `required` where the text has no cue is rejected.

The cue lists and heading lists are defined once, in `cues.py`, and are shared with the cue sentence coverage check (V13).

Known limits: negation is not understood ("not required" still counts as a required cue), and a cue word used in another sense can mislead the check. Both err toward rejecting, which is the safe direction.

## V4 Fact exists
`check_fact_exists(cited_ids, bank)`. Every cited ID must be a fact in the bank (verified or not). IDs match exactly, so `f-0001` or `F-0001 ` fail. An empty list passes, because requiring a citation at all is V9's job.

## V5 Fact verified
`check_fact_verified(cited_ids, bank)`. Every cited fact must have `verified_on`. An ID not in the bank cannot be verified, so it fails here as well as in V4.

## V6 Fact shareable
`check_fact_shareable(fact_ids, bank, hosted=...)`. With a local backend everything passes. With a hosted backend, any `local_only` fact fails. Pass every ID that was sent to the backend as well as every ID cited from it. Unknown IDs are left to V4.

## V7 Entity consistency
`check_entities(text, cited, bank)`. `cited` is the list of facts the text cites.
1. Dates: every year ("2019"), month and year ("March 2019", "Mar 2019") and ISO date ("2019-03", "2019-03-01") in the text must be a date of a cited fact (its `start` or `end`, in that form or a coarser one). Impossible ISO dates such as "2019-99" are ignored.
2. Names: the employer and role of every bank fact that was not cited, plus the tag names of uncited certification and education facts, must not appear in the text. Matching is whole word, case and width insensitive. Names that belong to a cited fact are blanked out first, so "Engineer" inside a cited "Backend Engineer" is fine.

Known limits: a name that is in no bank fact is V10's concern. Any four digit number from 1900 to 2099 reads as a year, so "2000 requests" must match a cited date. Both err toward rejecting.

## V8 Numeric consistency
`check_numbers(text, cited, requirement_text)`. Every number in the text must appear in a cited fact (claim, employer, role, tag names, or the year of its dates) or in the text of the requirement being answered. `extract_numbers` reads digits (commas, decimals, a leading minus, percents) and number words ("twelve", "twenty-three", "two hundred fifty"). So "40%" and "40" agree, "3.50" and "3.5" agree, and "-5" does not match "5". Fact and requirement IDs (`F-0001`, `R-12`) and names with digits (`k8s`, `python3`) are not numbers. ISO dates are left to V7. A lone "one" is not counted because it is usually a pronoun.

## V9 Citation required
`check_citation_required(claims)`. Each claim has `text` and `fact_ids` (any object with those attributes works). The first non-blank claim with no fact IDs fails and is named in the verdict.

## V10 Novel term flag
`novel_terms(text, cited, requirement_text)` lists suspicious terms, `check_novel_terms` fails if there are any. A term is suspicious if it looks like a name, tool or acronym and neither a cited fact (claim, employer, role, tags) nor the requirement text contains it. Looks like a name means: contains a digit, `+`, `#` or an inner dot (`node.js`), is ALLCAPS, is CamelCase, or is capitalized in the middle of a sentence. Months, weekdays, fact IDs and plain numbers are skipped, and a possessive matches its base word.

This is a heuristic and is deliberately conservative: it flags for review, it never proves a lie. It cannot see a novel word at the start of a sentence or a lowercase one ("terraform"). V7, V8 and V10 together gate the rationale text, which is shown to a human only if all three pass.

## Try it locally
```bash
uv run python -c "
from cypress_creek.ingest.models import Requirement
from cypress_creek.validators import REGISTRY
posting = 'Requirements:\n- 5 years of Postgres experience.\n'
req = Requirement(id='R-1', text='5 years of Postgres experience', span=(16, 46), kind='skill', term='postgres', importance='preferred')
print(REGISTRY['V2'].check(posting, req))
print(REGISTRY['V3'].check(posting, req))"
```
V2 passes and V3 fails, because the posting is under "Requirements:" and the model said `preferred`.
