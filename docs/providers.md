# Providers

The provider layer is how the pipeline talks to a model. Every backend (local or hosted) implements one interface, so the pipeline and the eval harness never know which one they use. Code is `src/cypress_creek/providers/`. This page covers the interface, the typed errors and the retry policy. Real adapters, the config that selects a backend and the factory arrive in later cards (see the issue board).

## The interface
`Provider` is a `typing.Protocol` in `providers/base.py`:
- `complete_structured(system, data_block, schema, max_output_tokens) -> StructuredResult[T]`. `schema` is a pydantic model class and `T` is that class.
- `count_tokens_estimate(text) -> int`.
- `capabilities`: a `Capabilities` with `context_tokens`, `strict_schema`, `local` and `cost_per_mtok` (a `CostPerMtok` of dollars per million input and output tokens, zero for local backends).

`system` and `data_block` are separate arguments on purpose. `system` is trusted and static. `data_block` is untrusted posting text, wrapped by the prompt builder in a random per request boundary. Keeping them apart means an adapter cannot merge them by accident. The fact bank is a separate trusted block, added by the prompt builder card.

`StructuredResult` carries `parsed` (the validated model), `raw_text` and `usage` (`Usage` with input and output tokens). The parsed model is still model output: nothing in it is trusted until the validators pass it.

## Typed errors
All in `providers/errors.py`, all subclasses of `ProviderError`. Callers branch on the class and never on the message text.

| Error | Fields | Retried? |
| --- | --- | --- |
| `ContextTruncated` | `input_tokens`, `context_tokens` | Never |
| `SchemaViolation` | `schema_name`, `detail` | Once, with only the schema error |
| `ProviderUnavailable` | `provider`, `reason` | No |
| `RateLimited` | `retry_after_seconds` (optional) | Bounded backoff |
| `BudgetExceeded` | `limit_usd`, `spent_usd` | Never |
| `Refusal` | `provider` | Never |

Keeping keys out of errors: `SchemaViolation.detail` and `ProviderUnavailable.reason` are free text, so both take an optional list of key values to hide and replace every non-empty one with `[redacted]` before storing it or building the message. An adapter passes its API key there. Keys are never logged and never put in an error.

## Retry policy
`call_with_retry(call, sleep=time.sleep, policy=RetryPolicy())` in `providers/retry.py` is the one place retries happen. `call` takes one argument: `None` on the first try and, after a `SchemaViolation`, that error's `detail` (the schema error text, never model output).
- `SchemaViolation`: retried once in total, then raised.
- `RateLimited`: up to `max_rate_limit_retries` (default 3) retries, waiting `retry_after_seconds` if the backend gave one, otherwise `base_delay_seconds * 2^attempt`, never more than `max_delay_seconds` (defaults 1 and 30).
- Every other error propagates at once.

The two counters are separate. `sleep` is injectable so tests never wait.

Known limits: there is no jitter in the backoff, and `count_tokens_estimate` is an estimate that each adapter defines.

## Try it locally
```bash
uv run python -c "from cypress_creek.providers import ProviderUnavailable; print(ProviderUnavailable('openai', 'bad key sk-123', secrets=['sk-123']))"
uv run python -c "from cypress_creek.providers import RateLimited, call_with_retry; outcomes = [RateLimited(retry_after_seconds=0.1)]; call = lambda feedback: (_ for _ in ()).throw(outcomes.pop()) if outcomes else 'done'; print(call_with_retry(call))"
```
The first prints `openai unavailable: bad key [redacted]`. The second waits a tenth of a second after one rate limit and prints `done`.
