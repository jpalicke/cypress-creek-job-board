# Pipeline

Stages are added here as their cards land. Everything in this file is deterministic: no model is called and nothing reads the clock (the caller passes `today`).

## Support rules (the support gate)
For each requirement the gate decides the most support the fact bank can ever justify. A model verdict later may confirm or downgrade this ceiling, never raise it.

1. **Candidates.** A verified fact is a candidate if one of its tags equals the requirement term or one of its aliases (see the alias table in [data-model.md](data-model.md)). Education and certification requirements only match facts of that kind. Skill requirements ignore those facts.
2. **No candidate** means support `none`, gate `no_candidate`, and the requirement goes in the gap list.
3. **Level.** If every matching tag is `familiar`, support is capped at `partial` (gate `familiar_level`).
4. **No years stated** (or an education or certification requirement): a candidate gives `strong` (gate `term_match`).
5. **Years stated.** The date intervals of all candidates are merged so overlapping roles count once, and a role with no end date runs to `today`.
   - merged years at or above the requirement: `strong` (gate `years_met`)
   - above zero but below: `partial` (gate `years_below`)
   - no usable dates: `partial` (gate `no_dates`)

The functions live in `src/cypress_creek/scoring/support.py`: `candidate_facts`, `merged_years` and `support_ceiling`. They read a requirement through a small protocol (`term`, `kind`, `years`), which the `Requirement` model from card B3 will satisfy.

## Try it locally
```bash
uv run python -c "
from datetime import date
from types import SimpleNamespace
from cypress_creek.facts import load_bank
from cypress_creek.scoring.aliases import load_aliases
from cypress_creek.scoring.support import candidate_facts, support_ceiling
req = SimpleNamespace(term='postgres', kind='skill', years=3)
bank, aliases = load_bank(), load_aliases()
found = candidate_facts(req, bank.verified_facts(), aliases)
print(support_ceiling(req, found, date.today(), aliases))"
```
