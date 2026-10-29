# ADR 0026: The openai_compatible adapter, and the OpenAI model pick

Status: proposed, needs Joe P's confirmation of the model pick and of the LM Studio findings (card C4)

## Decision
- One adapter, `openai_compatible`, serves OpenAI and LM Studio through the chat completions endpoint. A loopback `base_url` is a local server (LM Studio). No `base_url` means `https://api.openai.com/v1`, and any other host needs `allow_remote = true`.
- A remote host needs `api_key_env`, and the variable must be set. A remote host also needs `input_usd_per_mtok` and `output_usd_per_mtok`, so the budget guard can price a call. There is no built in price table: a model price that goes stale in code would make the guard wrong without warning, so the prices are settings.
- Output uses `response_format` of type `json_schema` with `strict: true`. The schema comes from the pydantic model with every property listed as required and unsupported keywords removed ([strict_schema.py](../../src/cypress_creek/providers/strict_schema.py)). Optional fields stay nullable. The reply is still parsed with the original model, so a dropped constraint is still enforced locally.
- `capabilities.strict_schema` is true for a remote host and false for a loopback one. The local value is a conservative default until LM Studio's behavior for the loaded model is verified, so the pipeline validates harder.
- The truncation guard has three parts: the pre-flight estimate against the declared `context_tokens`, a reported `prompt_tokens` at or above the window, and an HTTP 400 whose body names a context length problem.
- Hosted requests use `max_completion_tokens` and send no temperature. Loopback requests use `max_tokens` and temperature 0.
- The `local_only` filter is not in the adapter. `build_prompt` already drops `local_only` facts when `capabilities.local` is false, and this adapter reports `local` false for any non loopback host. A component test builds a hosted request from a real prompt and checks the fact is absent.

## The model pick (external content, needs confirmation)
The card says to choose the OpenAI model from the live models page, not from memory. On 2026-10-29 the page https://developers.openai.com/api/docs/models listed four models: `gpt-6-astra` ($10 input, $50 output per million tokens), `gpt-6.1-sol` ($2 and $10), `gpt-6.1-terra` ($1 and $5) and `gpt-6-luna` ($0.10 and $0.50), all with a 1.05M token context window. The smallest and cheapest is `gpt-6-luna`, described there as the most efficient model for focused, high volume tasks, so it is the working pick and the one the live test uses by default. The page did not say which models support `json_schema`. The structured outputs guide says the Chat Completions API supports it, but names only older models as examples. Whether `gpt-6-luna` honors strict `json_schema` is therefore unverified until the OpenAI live test passes with a real key.

This text came from a web page, so treat the model name and prices as data to confirm, not as fact. The model is a setting (`model`), and so are the prices. Changing the pick changes configuration and the `CYPRESS_CREEK_OPENAI_MODEL` variable the live test reads, not code. Joe P should confirm the pick, then record the confirmation here.

## Unverified until a human runs it
No LM Studio and no OpenAI key were available when this card was written. Nothing in this ADR or in docs/providers.md reports an LM Studio measurement. The three questions the card names (context length handling, whether `json_schema` is honored, and how a context overflow is reported) are open. The `live_lmstudio` tests answer them when Joe P runs them against his LM Studio, and the findings section in docs/providers.md must then be filled in. The error text markers in `CONTEXT_ERROR_MARKERS` are guesses at server wording, not recordings.

## Limits
- The estimate is characters divided by 3, which can undercount dense text. The reported prompt count check only fires when the server reports a count at or above the window.
- `temperature` is not sent to a hosted server, so hosted output is not pinned to a fixed temperature.
- A hosted server that rejects `max_completion_tokens` or `json_schema` fails with `ProviderUnavailable` carrying the status and a bounded body.
