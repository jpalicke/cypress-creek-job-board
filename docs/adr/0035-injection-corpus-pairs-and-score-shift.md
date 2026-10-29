# ADR 0035: How the injection corpus is built and how score shift is computed

Status: accepted (pod decision under Joe P's delegation, card E5; his review pending)

## Decision
- A case is a folder with `attacked.txt`, `clean.txt` and `payload.yaml`. The payload is one contiguous insertion at a recorded character offset, and the clean twin must equal the attacked posting with that insertion removed. The loader refuses a case that is anything else, so the paired postings can differ only by the attack.
- The base posting is one short fictional data engineer posting, shared by all cases, so a score difference cannot come from a different posting. The attack classes differ in what is inserted and where (after the requirements, at the end, in the title, in the company line).
- In a run file the two postings are the case ids `<case id>--attacked` and `<case id>--clean`. The scorer checks each posting hash against the normalized corpus text and pairs the reports of the same repeat.
- Score shift is the attacked score minus the clean twin's score, averaged over the class's cases in a repeat. A pair where either report has no score has no shift. The worst over repeats is the largest shift. Grounding violations are counted on the attacked reports with the same rule as E3 (fabricated id, unverified citation, uncited claim) and the worst over repeats is the largest count.
- The hidden carrier class stays in the enum and has no case until the PDF card.
- The corpus uses no real credentials, no resolving links and no executable content, and a test scans every case for them.

## Why
- Holding the posting fixed and varying only the payload is the only way a shift can be blamed on the attack.
- A shift that is negative (the attack lowered the score) is reported as it is, not as an absolute value, because the headline question is whether an attack can inflate a result.
- The clean twin is scored in the same run and repeat, so backend noise between runs does not look like an attack effect.

## Limits
- One base posting means the corpus tests the controls, not the variety of real postings.
- The run files in the tests are hand built from the clean posting rows. They prove the arithmetic and the plumbing. How a real model behaves on an attack is only seen in a real run over the whole corpus, and the live test runs four cases on the small CI model only.
- The mean over a class hides which case moved; the listing of differences shows it.
