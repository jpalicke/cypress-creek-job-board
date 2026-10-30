# ADR 0025: Anthropic adapter uses native structured output

Status: accepted (card C5)

## Decision

- Return JSON with the Messages API's native structured output (`output_config.format` of type `json_schema`), not a forced tool call. The models overview and error pages say `claude-sonnet-5-5` rejects `tool_choice` of `any` or `tool` with a 400, so forced tool use is not available for the default model. The adapter offers no tools at all, which keeps the "model has no tools" rule true on the wire.
- Send the trusted system text as the top level `system` string and the untrusted data block (posting inside its boundary, then any trusted facts) as the one user message. They are never merged.
- Rewrite the pydantic schema before sending: close every object with `additionalProperties: false` and drop the keywords the grammar rejects (`minimum`, `maximum`, `exclusive*`, `multipleOf`, `minLength`, `maxLength`, `maxItems`, `pattern`, `uniqueItems`, and `minItems` above 1). Nothing is lost as a check, because the pydantic model still validates every answer and a mismatch is a `SchemaViolation`.
- Read only `text` content blocks, so adaptive thinking blocks are ignored. The `stop_reason` decides the error: `refusal` is `Refusal`, `max_tokens` is a `SchemaViolation` (retried once with only the error text), anything else but `end_turn` is `ProviderUnavailable`. A stop reason is never echoed unless it looks like a plain identifier.
- Error mapping: 429 and 529 are `RateLimited` (with `retry-after` when sent). A 429 whose body carries `enforced_spend_limit_reached` is `ProviderUnavailable`, because retrying cannot succeed until the cap resets. Every other non-200 status is `ProviderUnavailable` with the status, the error type, a short scrubbed message and the `request-id` when it is well formed. Every free text field is scrubbed of the key.
- Usage comes from the response (`input_tokens` plus any cache token fields, and `output_tokens`). A response without complete counts is an error, so the budget guard cannot be fed a guess.
- Hosted rules: `allow_remote = true` is required for the built in URL, a remote `base_url` must be https, the key comes only from the variable `api_key_env` names, and redirects are not followed so the key cannot travel to another host.
- Prices: `claude-sonnet-5-5`, `claude-opus-5-5` and `claude-fable-5-1` have documented defaults from the models overview. Any other model needs `input_usd_per_mtok` and `output_usd_per_mtok` in the settings, so a budget never runs on a guessed price. The context window defaults to the documented 1,000,000 tokens unless `context_tokens` is set.

## Why

Native structured output constrains the answer to the schema without a tool round trip, works on the default model, and leaves no tool surface for injected text to aim at. The rewrite is the shared `strict_schema` with the Anthropic keyword set (`ANTHROPIC_UNSUPPORTED_KEYWORDS`), so the two hosted adapters have one rewriter and two named sets. Dropping unsupported keywords is safe because the validators and the pydantic model are the real control, as for every backend.

## Limits

- **The real structured call was accepted by the live API on 2026-10-30.** Joe P ran `uv run pytest tests/integration/test_anthropic_live.py -q` once with a real key and both tests passed (the wrong-key 401, which proves the endpoint, the version header and the auth path, and the real structured call). Tracked in [issue #129](https://github.com/jpalicke/cypress-creek-job-board/issues/129).
- Refusal fallbacks to another model are not used, on purpose: an eval needs the model identity to stay fixed.
- The `anthropic-version` header is `2023-06-01`. The body sends no sampling fields, so moving to a newer API version later is a header change, to be done deliberately.
- 529 (overloaded) maps to `RateLimited` and uses the retry layer's default backoff when no `retry-after` is sent.
- Thinking is left at the model default (adaptive). Thinking tokens count against `max_tokens`, so a small output cap can end with `max_tokens` and a `SchemaViolation`. Raise the cap rather than disabling thinking, because the accepted `thinking` values differ by model.
- The token estimate is characters divided by two. It runs high for prose and is only used for the pre-flight check and the budget guard; real usage is recorded after each call.
- The live test needs a real key and spends a fraction of a cent. It fails, never skips, without one. The component tests exercise the same code over real HTTP against a local server that plays hand written responses in the documented shape; they prove our handling, not Anthropic's behavior.
- Prompt caching, batching and streaming are out of scope.

See [providers.md](../providers.md#the-anthropic-adapter).
