# E3 label decisions

Joe P delegated the E3 hand labels to the pod. This page explains every judgment call so he can review the labels and order changes. A changed label is not a mistake, it is the product call. The labels were written by Claude. Joe P reviewed them on 2026-10-30 (in chat, after reading this page and a sample fixture, and after the explanation that the sample bank is a fictional candidate whose gaps, Java among them, are deliberate) and said they look fine; each `labels.yaml` now says `review: reviewed`. He can still order any change.

## How the labels were made
- Each posting was read as plain text, and each label was written from that text and from `evals/bank/sample_bank.yaml` and `PLANTED_GAPS.md` alone.
- No model, no pipeline stage and no support gate was run on a posting before its labels were written. Model output was never used to fill or check a label. `model_output_used: false` is part of the schema and the validator refuses anything else.
- The only machine checks run afterwards are structural: spans are exact posting text, fact IDs exist and are verified and shareable, planted gap rows agree, and every sentence holding a cue word is listed. They check the label file against the posting and the bank. They never decide a label.
- Labels were not tuned to any backend, and none has been run.

## The rubric
Each requirement has a verbatim span, a kind, a normalized term, optional years and issuer, an importance and the expected support.

- **Strong:** a verified, shareable fact shows the term directly, at a level above familiar, with enough dated years if the posting states years.
- **Partial:** a fact touches the term but is familiar level only, self attested, too short, or covers part of what is asked.
- **None:** no verified, shareable fact shows it. Adjacent work is not enough. A fact that is local only, or unverified, never counts.
- **Status** is `gap` unless support is strong. That matches the report, whose gap list holds every requirement that is not strong.
- **Importance** follows how a person reads the posting: items under "What you'll bring" or "What We Require" are `required`, items under "What We Value", "Optional" or marked a plus or beneficial are `preferred`, and duties and technology lists are `unspecified`.
- **Alternatives** such as "Python, Bash, or Go" are one requirement. The label cites the fact that satisfies one of them.
- **Shared spans:** where one sentence lists several terms, several labels share the span and differ in term. A list of five products is labeled as one requirement when a human would treat it as one demand.
- **Cue sentences** are the sentences that hold a cue word from `validators/cues.py`. Each is `covered` (a requirement must touch it) or `not_a_requirement`.

Not labeled on purpose: company boilerplate, benefits, pay, equal opportunity text, team descriptions, and generic duties that name no skill or tool (for example "collaborate with Product"). Duties that name a concrete tool or skill are labeled.

## Judgment calls to review first
These are the labels I am least sure of, in rough order of how much they would move the numbers. Each also carries a `Flagged for review` note in its `labels.yaml` where it applies.

1. **Importance versus the cue check (V3).** The pipeline's V3 check forces importance to follow cue words and recognized headings, so "What you'll bring" lists come out `unspecified` there. I labeled importance the way a person reads the posting, as the card says. Importance agreement will therefore look low for a model that obeys V3. If you want the product definition instead, change every `required` and `preferred` under a non cued heading to `unspecified`. Say so and I will redo it.
2. **Tag vocabulary versus human reading.** The bank tags F-0012 `fastapi`, so a tag match on "REST APIs" finds nothing, yet building REST APIs is exactly what the fact says. I labeled it strong. The same goes for performance tuning (F-0016, F-0003) and documentation (F-0024). If you want labels to follow tag matching only, these become none.
3. **CI/CD.** The alias table maps `ci/cd` to `ci`, and F-0013 shows CI only. I labeled strong. The delivery half is not shown, so partial is arguable.
4. **Soft skills.** I labeled communication partial where a fact shows a part of it (F-0021 a meetup talk, F-0024 an onboarding guide), and other soft items none. These are the most subjective labels in the set.
5. **Own library as open source contribution.** F-0008 is the candidate's own public library. For "open source contributions" I labeled partial, and for "contribution to open source" under a values line I labeled none.
6. **Local only fact.** For "respond to incidents" the only matching fact is F-0007, which is local only and never shown to a model. The expected result is a gap even though a human could claim it. This is deliberate and tests the sharing rule.
7. **Bundled lines.** "Kafka, Cassandra, Elasticsearch and Spark" and "Java, C++, Python, Rust, or similar" are labeled as one requirement per term group. A model that splits them will score lower precision. Granularity is a call, not a fact.
8. **Location and clearance lines.** "You must work from the city..." and "you are required to work from an office" hold cue words but are work arrangement rules. I marked them `not_a_requirement`, so the omission check will flag them and the report should list them as not assessed. Security clearance is labeled a preferred certification with no support.
9. **Negation.** "beneficial, but not required" holds the cue word "required". I labeled it `covered` with a preferred requirement. The cue check does not read negation.
10. **Cloud provider.** "AWS, Google Cloud, or Microsoft Azure" is one requirement, term `cloud provider`, so it does not reuse the planted `skill:aws` row. If you want that row exercised, I can add a second label for it.

## The postings
Six postings, from the approved list of eight. The remaining two are Ashby postings, held out for later as the card says. Fixture folders are named `<ats>-<job id>` and use the IDs the boards publish.

| Fixture | Role | Labels | Strong / partial / none | Planted gap rows hit |
| --- | --- | --- | --- | --- |
| `greenhouse-8701290002` | Support engineer | 13 | 4 / 2 / 7 | kubernetes |
| `greenhouse-8704363002` | Python backend engineer | 14 | 4 / 1 / 9 | none |
| `greenhouse-8778943002` | Database backend engineer | 11 | 2 / 2 / 7 | none |
| `greenhouse-8889193002` | Cloud platform engineer | 14 | 2 / 5 / 7 | kubernetes, terraform |
| `lever-10dfc8bc-99ad-4ca2-ab76-853cb90a92c2` | Backend software engineer | 23 | 9 / 3 / 11 | java, rust, go, kubernetes |
| `lever-aaee4d20-7f1b-48b1-ad23-d52ffbf42a49` | Backend infrastructure engineer | 24 | 4 / 4 / 16 | java, rust, go, kubernetes |

The mix is gap heavy on purpose: real postings ask for far more than a small bank covers. No posting exercises the `python` 10 year, `sql` 10 year, `dbt` or statistics certification rows, because none of the six states those requirements.

## The 404s and the replacements
The approved list had four Greenhouse postings and two Lever postings in the first six. On 2026-10-29 each was re-fetched with an honest `cypress-creek` User-Agent, one request every two seconds.

| Approved ID | Result | Replacement | Why this one |
| --- | --- | --- | --- |
| Greenhouse 8701290002 | 200, kept | none | |
| Greenhouse 8698314002 | 404 `Job not found`, and absent from the board listing | 8704363002 | Python, API and testing requirements overlap the bank |
| Greenhouse 8512220002 | 404, absent from the listing | 8778943002 | A strong PostgreSQL requirement beside a Ruby gap |
| Greenhouse 8731564002 | 404, absent from the listing | 8889193002 | Kubernetes, Terraform and cloud requirements land on thin and missing support |
| Lever 10dfc8bc-99ad-4ca2-ab76-853cb90a92c2 | 200, kept | none | |
| Lever ac978161-6f46-4f6b-ad9e-a258e642751c | 404 | aaee4d20-7f1b-48b1-ad23-d52ffbf42a49 | Infrastructure and data systems requirements differ from the other Lever fixture |

I checked that the Greenhouse job URL shape works by fetching 8701290002 successfully, so the three 404s are real closures, not a wrong URL. The earlier first attempt at 8698314002 was the same 404. Replacements came from the same boards and were picked for coverage of the bank, before any label was written. Each replacement records the original ID and the reason in its `meta.yaml` under `replaces`. I skipped one Lever candidate, a fellowship posting, because its text is mostly political and not a role. Postings whose titles name a sector were skipped in favor of neutral ones.

## Changing a label
Edit the `labels.yaml` of the fixture and run:
```bash
uv run pytest tests/component/test_labels.py tests/component/test_fixtures.py -q --no-cov
```
The validator reports every problem at once. Change `review` to `reviewed` only after Joe P has been through the file. A label change after any model run is a new label version: record it, and keep the earlier run files, as the E8 method rules require.
