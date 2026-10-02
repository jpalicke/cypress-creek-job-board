# ADR 0010: How stage 1 extraction trusts the model

Status: accepted (Joe P, card D2)

## Decision
- The model proposes requirements. It never supplies offsets, ids or the importance that counts. Code finds each proposed text in the posting, assigns `R-n` ids, and sets importance from the cue words (the V3 rule). Text that is not in the posting is dropped with a reason.
- A typed provider failure (schema violation after the one retry, context truncated, backend unavailable, rate limited, refusal) gives an `incomplete` result with no requirements and a failure label. Nothing is guessed to fill the gap. `BudgetExceeded` is not swallowed: it propagates and stops the run.
- The output cap is the smaller of 4000 tokens and half the context window.
- The retry feedback (the schema error text) joins the trusted system message and never the data block. It does not change `prompt_hash`, so one prompt version keeps one hash.
- The wording moved to `extract_v2.txt`. Released templates are not edited.

## Why
- A model that gives a span can give a wrong one. Searching for the text itself removes that failure and leaves V2 as a backstop.
- The first live run against `qwen3.5:0.8b` answered `"issuer": "none"`, so v2 says to use null. The same run had the pre-flight refuse a short posting: a fixed 4000 token output cap plus the prompt did not fit a 4096 token window. Half the window always leaves room for the prompt.
- An incomplete result is honest. A report built on a partial list would claim coverage it does not have.

## Limits
- The first occurrence rule can attach a repeated sentence to the wrong copy. The span is still verbatim.
- `kind` and `term` come from the model. Later stages check term support, not this one.
- An output cut by the cap fails the schema and ends as `schema_violation`. For 40 requirements a 4096 token window is tight, so use a larger window for long postings.
- The retry wiring runs only against a real model. A real schema failure cannot be produced without a fake server, which this repo does not allow.
