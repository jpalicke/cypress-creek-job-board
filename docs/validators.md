# Validators

The validators are the control that makes the grounding promise true even if the model is hostile. Every model output is attacker-controlled data, and these pure functions (no model, no network, no clock) decide whether it may be used. The eval harness runs the same functions, so production and evals cannot disagree about what "grounded" means.

All of them live in `src/cypress_creek/validators/`. Each returns a `Verdict` (`validator`, `passed`, `reason`, `offending`). `REGISTRY` in `validators/registry.py` lists every validator by id so a harness can look one up and run it.

## Catalogue
| Id | Name | Rejects | Module |
| --- | --- | --- | --- |
| V1 | Schema | Malformed or extra-field output | `extraction.py` |
| V2 | Verbatim span | Invented or altered requirements | `extraction.py` |
| V3 | Importance cues | A model promoting or demoting a requirement | `extraction.py` |

More are added as they land (V4 to V14 are in the same card).

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
