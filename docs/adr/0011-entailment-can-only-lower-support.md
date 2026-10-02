# ADR 0011: How stage 3 entailment can change support

Status: accepted (Joe P, card D4)

## Decision
- The model's verdict is a second opinion. The final support is the lower of the rule ceiling and the verdict (`supports` is strong, `partial` is partial, `does_not_support` is none). It can never be higher than the ceiling. A verdict above the ceiling is clamped and counted as a raise attempt.
- `Match` refuses support above its ceiling and allows a drop of any size. This replaces the one step limit in [ADR 0003](0003-score-formula-and-downgrade-only.md). `downgrade()` keeps its one step meaning.
- The requirement text goes in the untrusted data block. The candidate facts follow it in a separate trusted block, so a fact is never inside the boundary and never in the system message.
- A `supports` or `partial` verdict needs at least one valid citation: the id exists (V4), is verified (V5) and was one of the candidates sent. Without one the verdict is `does_not_support`.
- The rationale is display text only. It is shown only if V7, V8 and V10 pass (and V9 for a positive verdict, since a does_not_support verdict has nothing to cite), and is otherwise replaced by "rationale withheld: failed grounding check".
- A typed provider failure keeps the rule ceiling and marks the requirement not model checked. A requirement with no candidates makes no call and is marked as not needing one. `BudgetExceeded` propagates.

## Why
- The card and the spec disagreed: the card has `does_not_support` take `strong` to `none`, while the spec and `Match` said one step. A cap at `partial` would give half credit to a claim the model says is unsupported, so the lower of the two wins.
- Clamping in code, not in the prompt, is what makes the downgrade only promise true. The prompt asks for strictness, the code does not rely on it.
- Keeping the facts out of the boundary and out of the system message means a hostile posting cannot pose as a fact and a fact cannot pose as an instruction.
- A model that cites nothing has shown nothing, so it cannot confirm support.

## Limits
- The validators check numbers, dates, names and novel terms in the rationale. They do not check that the rationale is a good argument, which is why it is display only and never changes support.
- A model can be too strict. That costs the user a lower score, never an inflated claim.
