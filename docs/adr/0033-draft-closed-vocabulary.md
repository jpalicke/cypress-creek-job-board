# ADR 0033: Drafts use a closed vocabulary, and V8 reads quantity words

Status: proposed (issue #131, pending PR review)

## Decision

- A draft sentence may only use words that a cited fact uses. This is a strict form of V10, `check_novel_terms(..., closed_vocabulary=True)`, and only drafts turn it on. Every word of the sentence must appear in the text of a cited fact (claim, employer, role, issuer, tag names and levels) or in the requirement text when a caller passes one (drafts pass none). The exceptions are a fixed list of 32 connectives (`FUNCTION_WORDS` in `validators/vocabulary.py`, without `by`: "was led by a team" would invert who led whom), month names (V7 reads them with the year) and numbers written as digits or words (V8 reads them).
- Matching uses a small inflection rule: `ing` or `ed` is dropped, then a final `e` and a doubled final consonant, so "migrating", "migrated" and "migrate" agree while "manager" and "manage", or "led" and "lead", do not. A plural is a different word ("teams" needs a fact that has "teams"), because plural stemming let "Led teams ... billing systems" through. Possessives drop `'s`. A hyphen splits a compound, so each part needs a fact. Words are compared after NFKC and with format characters removed.
- Any non-ASCII character in a draft sentence that no cited fact itself uses fails the sentence: Cyrillic or full width look-alikes, zero width and soft hyphen characters, and other invisible characters. What a person copies is therefore exactly what was checked.
- A negation that a cited fact makes ("Never missed a date") and the sentence drops fails too, because every word of the sentence could still be in the facts.
- V8 also reads quantity words with no digit (decade, dozen, couple, half, double, triple, quadruple, hundreds, thousands, millions, billions, numerous): a cited fact or the requirement text must use them. This applies everywhere V8 runs, including entailment rationales.
- No new validator id is added (V1 to V14 stay the spec's set), no model is involved and the check is deterministic. A failing sentence is shown as NOT VERIFIED and is never in `clean_sentences`.

## Why

The first version of this fix used word lists for impact, rank and negation words. A reviewer found twenty unlisted siblings in minutes ("spearheading", "head of", "halving", "many years", a Cyrillic letter, a zero width space), because each class has an open set of synonyms and spellings. A word list cannot close that. The prompt already tells the model to paraphrase using only the facts' words, so the check enforces that rule literally and fails safe. The lists for impact and rank words were removed because they added nothing once the vocabulary is closed.

## Cost

An honest rewording that uses a word the fact does not use is flagged and needs a human look. On a hand written corpus of 22 honest rewordings of the sample bank facts (`tests/unit/validators/test_vocabulary_corpus.py`), 10 are flagged (45 percent). Each swaps in a word the fact lacks ("Developed", "Reduced", "Managed", "Earned") or is a capitalized hyphen compound. The prompt now asks the model to reuse the facts' wording and change only order and connectives, which should lower the live rate; the corpus pins today's number so a later change to the lists or the stem rule shows up as a diff.

V8 quantity words now also withhold some entailment rationales, for example a rationale that says "half of the requirement" or "a couple of facts" when neither the cited facts nor the requirement use the word. That fails safe, but it can lower the rationale acceptance numbers the E lane measures, so a later drop in that metric can be traced to this change.

Tag levels count as fact words (`working`, `familiar`, `expert`), so a sentence "Worked with Docker" is allowed for a `working` Docker tag. That matches what the fact says.

## What it does not prove

Meaning is not read. A recombination of cited words can still mislead ("Led Python engineers to a billing team of 8" uses only fact words, as does "Led 8 billing system", which the tests pin as a limit), a correct number can be attached to the wrong thing, and citing an unrelated verified fact still passes V4 to V9. A clean line means only "no check found a problem", so `needs_human_review` stays true and every draft is read against the person's own record.

See [validators.md](../validators.md#v10-novel-term-flag) and [pipeline.md](../pipeline.md#draft-help).
