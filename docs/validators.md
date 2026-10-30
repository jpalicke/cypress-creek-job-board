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
| V11 | Requirement cap and dedupe | Requirement stuffing to inflate a score | `requirements.py` |
| V12 | Date sanity | Future dates and a start after the end | `fact_dates.py` |
| V13 | Cue sentence coverage | Requirements silently dropped or hidden by injection | `requirements.py` |
| V14 | Company name shape | URLs, slugs or injected text in company suggestions | `names.py` |
| V15 | Resume grounding | A fact proposed from a resume that says more than the resume | `candidates.py` |

All fifteen exist. The hostile corpus that every one of them is tested against lives in `tests/fixtures/hostile_outputs/`.

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
2. Names: the employer and role of every bank fact that was not cited, plus the tag names and issuer of uncited certification and education facts, must not appear in the text. Matching is whole word, case and width insensitive. Names that belong to a cited fact are blanked out first, so "Engineer" inside a cited "Backend Engineer" is fine.

Known limits: a name that is in no bank fact is V10's concern. Any four digit number from 1900 to 2099 reads as a year, so "2000 requests" must match a cited date. Both err toward rejecting.

## V8 Numeric consistency
`check_numbers(text, cited, requirement_text)`. Every number in the text must appear in a cited fact (claim, employer, role, issuer, tag names, or the year of its dates) or in the text of the requirement being answered. `extract_numbers` reads digits (commas, decimals, a leading minus, percents) and number words ("twelve", "twenty-three", "two hundred fifty"). So "40%" and "40" agree, "3.50" and "3.5" agree, and "-5" does not match "5". Fact and requirement IDs (`F-0001`, `R-12`) and names with digits (`k8s`, `python3`) are not numbers. ISO dates are left to V7. A lone "one" is not counted because it is usually a pronoun.

Quantity words are checked too: `decade`, `dozen`, `couple`, `half`, `double`, `triple`, `quadruple`, `hundreds`, `thousands`, `millions`, `billions` and `numerous` (and their inflections, such as "doubling") must be used by a cited fact or the requirement text, so "for a decade" fails against a fact that gives no duration. Hyphenated words such as `double-checked` are whole words and are ignored. The list is finite, and drafts are held to a stricter closed vocabulary (see V10).

## V9 Citation required
`check_citation_required(claims)`. Each claim has `text` and `fact_ids` (any object with those attributes works). The first non-blank claim with no fact IDs fails and is named in the verdict.

## V10 Novel term flag
`novel_terms(text, cited, requirement_text)` lists suspicious terms, `check_novel_terms` fails if there are any. A term is suspicious if it looks like a name, tool or acronym and neither a cited fact (claim, employer, role, issuer, tags) nor the requirement text contains it. Looks like a name means: contains a digit, `+`, `#` or an inner dot (`node.js`), is ALLCAPS, is CamelCase, or is capitalized in the middle of a sentence. Months, weekdays, fact IDs and plain numbers are skipped, and a possessive matches its base word.

This is a heuristic and is deliberately conservative: it flags for review, it never proves a lie. It cannot see a novel word at the start of a sentence or a lowercase one ("terraform"). V7, V8 and V10 together gate the rationale text, which is shown to a human only if all three pass.

`check_novel_terms(text, cited, requirement_text, closed_vocabulary=True)` is the strict form that drafts use. Every word of the sentence must come from a cited fact (claim, employer, role, issuer, tag names and levels) or the requirement text when one is passed, apart from a fixed list of connectives, month names and numbers. A synonym, a made up result, a rank or a negation word that is not in the facts therefore fails without a growing word list. Rules, all in `validators/vocabulary.py`:

- **Function words** (the whole list, reviewed): a, an, the, of, to, in, on, at, for, with, and, as, from, using, while, its, their, into, that, which, who, was, were, is, are, been, it, this, these, those, through, via. Words that can carry a claim (no, not, never, only, first, more, most, all, every, many, over, or, but) are not on it, and neither is `by`, because "was led by a team" turns who led whom around.
- **Inflection**: `ing` or `ed` is dropped, then a final `e` and a doubled consonant, so "migrating", "migrated" and "migrate" agree, but "manager" and "manage", or "led" and "lead", do not. A plural is a different word: "teams" needs a cited fact that has "teams" (a fact with "team" does not allow it). A possessive drops `'s`. A hyphen splits a compound, so each part needs a fact.
- **Characters**: after NFKC and without format characters, words are compared lower case. Any non-ASCII character in the sentence that no cited fact itself uses (a Cyrillic or full width look-alike, a zero width or soft hyphen character) fails the sentence, so what is copied is what was checked.
- **Negation**: if a cited fact negates something ("Never missed a date") and the sentence has no negation word, V10 fails it as a dropped negation. An honest rewrite such as "without downtime" to "with zero downtime" is flagged too; that is safe and costs a human look.
- **Cost**: on 22 honest rewordings of the sample facts, 10 are flagged (45 percent), each because it swaps in a word the fact does not use. See [ADR 0033](adr/0033-draft-closed-vocabulary.md).

It is off for rationales, which may legitimately say "the facts do not show". Known limits: meaning is not read, so a recombination of cited words can still mislead ("Led 8 billing system" uses only words of the fact);  a correct number can be attached to the wrong thing; and a tag level word (`working`, `expert`) counts as a fact word. A clean line means only that no check found a problem, so a draft always stays under human review.

## V11 Requirement cap and dedupe
`dedupe_requirements(requirements)` keeps the first requirement for each normalized term (same rules as the alias table, so "PostgreSQL" and " postgresql. " are one) and at most 40 (`MAX_REQUIREMENTS`). It is idempotent, never reorders and never adds. `check_requirement_cap(requirements)` is the verdict form: it fails on more than 40, or on two requirements sharing a normalized term. A posting stuffed with repeated requirements therefore cannot inflate a score.

## V12 Date sanity
`check_fact_dates(fact, today)`. Wraps `date_problems` in `facts/dates.py`, the same rules the bank loader applies: no `start`, `end` or `verified_on` after `today`, and `start` not after `end`. `today` is passed in so the function stays pure. The verdict's `offending` is the field name.

## V13 Cue sentence coverage
`check_cue_coverage(posting_text, requirements)` fails if a posting sentence holding an importance cue word (the lists in `cues.py`, shared with V3) is not touched by any requirement span. The trace records this verdict after successful extraction. `uncovered_cue_spans(text, spans)` returns all original character offsets; `uncovered_cue_sentences` returns their text. The report lists each missed sentence with reason `cue_sentence_uncovered`, and the text view shows the count beside the score. The warning does not change score arithmetic or report status. A line that is only a section heading ("Nice to have:") is skipped. Partial overlap counts as covered.

Try the coverage check without a model:
```bash
uv run python -c "from cypress_creek.validators.requirements import uncovered_cue_spans; text='You must know Python. Postgres is required.'; print([(text[a:b], (a, b)) for a, b in uncovered_cue_spans(text, [(0, 21)])])"
```
It prints the uncovered Postgres sentence and its original offsets.

## V14 Company name shape
`check_company_name(name)`. After NFKC normalization the name must be 2 to 60 characters, at most 6 words, made only of letters, digits, spaces and `& . ' - ,`, in one script (so a Cyrillic lookalike letter inside a Latin name fails). It must not look like a web address (a dot followed by letters, so `acme.io` fails), a slug (one lowercase word with a hyphen), or be only digits.

Known limit: a short plain phrase such as "Ignore previous instructions" has the shape of a name. The shape check removes URLs and long injected text, and the company filter, resolver and human review handle the rest.

## V15 Resume grounding
`check_candidate_grounded(resume, fact)` (version 1) checks one fact proposed from a resume. The resume is the normalized text the model was given. The checks run in this order and the first failure is the verdict (`reason`, with the offending token for logs only):
1. `source_not_in_resume`: the source span, with spaces collapsed, must be a continuous piece of the resume. It is case sensitive and exact, so a lookalike letter or a changed word fails.
2. `number_not_in_source`: every number in the claim (digits with their separators, so `1,200` is not `1,200,000`) and every quantity word (such as dozen or decade) must be in the source.
3. `month_not_in_source`: every capitalised month name or abbreviation in the claim must be a month named in the source.
4. `name_not_in_source`: every capitalised word of the claim must be a word of the source, compared by case folding only. This includes the first word of the claim, so a claim must reuse the resume's own opening word. The pronoun `I` is exempt.
5. `tag_not_in_source`: every tag must be in the source, as the tag or as one of its aliases from `config/aliases.yaml`. The term must stand alone, so `c` is not found in `company` or `java` in `JavaScript`.

Known limits: a claim can be true to its words and still mislead by what it leaves out; lower case words are not checked (a wrong verb or tool in lower case passes if its capitalised and numeric parts are grounded), and number words such as "five" are only caught when they are in the quantity list. A person reads every candidate. The check is strict on purpose: a proposal that fails is dropped and counted, never repaired.

## The hostile output corpus
`tests/fixtures/hostile_outputs/` holds hand written bad model outputs, at least one JSON file per validator (`v01_...json` to `v15_...json`), each with a `validator`, a `description` and the `input` it is run with. Examples: an extra field carrying an instruction (V1), a fabricated fact ID (V4), an employer swapped between two real facts or a certification credited to the wrong issuer (V7), 40% inflated to 90% (V8), an uncited claim (V9), injected text echoed back with tools never used (V10), a tracking URL as a company name (V14). `bank.json` is the small fact bank the cases cite. `grounded_rationale.json` is a faithful output that must pass V7 to V10, so the tests cannot pass by rejecting everything.

`tests/unit/validators/test_hostile_corpus.py` runs every case through `REGISTRY` and fails if any validator has no case. To add a case, drop a new `vNN_name.json` next to the others. A new validator also needs a runner in that test and a row in `test_hostile_table.py`.

Run it:
```bash
uv run pytest tests/unit/validators -q
```

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
