# ADR 0003: Score formula, what supported means, downgrade only

Status: accepted (Joe P, card B5), pending approval

## Decision
- `score = 100 * sum(weight * value) / sum(weight)` over every requirement. Weights are required 3, unspecified 2, preferred 1. Values are strong 1.0, partial 0.5, none 0.0.
- "Supported" means strong or partial. The result also reports the count per level so a partial is never presented as a full match.
- Zero requirements gives `score = None` ("no score"). All `none` gives 0. These are different states and never collapse into each other.
- A `Match` carries both the gate `ceiling` and the final `support`. Construction refuses support above the ceiling and support more than one step below it. `downgrade()` lowers one step and stops at none. Nothing raises support.
- Overrides are a validated `Weights` instance, and the weights used are echoed in the result.

## Why
The score must be explainable by hand and must not be gameable by model output. Enforcing the ceiling in the type that scoring consumes means a model verdict that tries to raise support fails loudly instead of inflating a number. The one step limit matches the entailment stage, which confirms or downgrades, never rewrites.
