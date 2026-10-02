# Providers

The provider layer is how the pipeline talks to a model. Every backend (local or hosted) implements one interface, so the pipeline and the eval harness never know which one they use. Code is `src/cypress_creek/providers/`. This page covers the interface, the typed errors, the retry policy, the config that selects a backend and the Ollama adapter. The other adapters arrive in later cards (see the issue board).

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
| `BudgetExceeded` | `limit_name`, `limit`, `would_reach` | Never |
| `Refusal` | `provider` | Never |

Keeping keys out of errors: `SchemaViolation.detail` and `ProviderUnavailable.reason` are free text, so both take an optional list of key values to hide and replace every non-empty one with `[redacted]` before storing it or building the message. An adapter passes its API key there. Keys are never logged and never put in an error.

## Retry policy
`call_with_retry(call, sleep=time.sleep, policy=RetryPolicy())` in `providers/retry.py` is the one place retries happen. `call` takes one argument: `None` on the first try and, after a `SchemaViolation`, that error's `detail` (the schema error text, never model output).
- `SchemaViolation`: retried once in total, then raised.
- `RateLimited`: up to `max_rate_limit_retries` (default 3) retries, waiting `retry_after_seconds` if the backend gave one, otherwise `base_delay_seconds * 2^attempt`, never more than `max_delay_seconds` (defaults 1 and 30).
- Every other error propagates at once.

The two counters are separate. `sleep` is injectable so tests never wait.

Known limits: there is no jitter in the backoff, and `count_tokens_estimate` is an estimate that each adapter defines.

## The Ollama adapter
Code is `src/cypress_creek/providers/ollama.py`, registered as provider `ollama`. It uses Ollama's native `/api/chat` endpoint, not the OpenAI compatible one, because only the native one sets the context window per request. Decisions and measurements are in [ADR 0008](adr/0008-ollama-truncation-signature-and-window-floor.md).

Why it matters: when a prompt is longer than the window, Ollama does not fail. It silently drops most of the start of the prompt, which is where the trusted instructions live, and answers anyway. The adapter guards against that twice:
1. **Before the call.** It estimates tokens for the system text, the data block and the schema, adds the output cap, and raises `ContextTruncated` without calling the model if the total exceeds `context_tokens`. The estimate is the character count divided by 3, rounded up. Real text averages nearer 4 characters per token, so the estimate runs high and the guard errs toward refusing.
2. **After the call.** It compares the `prompt_eval_count` the server reports with the estimate. A count near the full window, or a count of about half the window (what a truncating server reports, measured on Ollama 0.34), that the estimate did not predict raises `ContextTruncated`. A response with no usage counts is an error.

Every request sets `num_ctx` from `context_tokens` (default 8192, minimum 2048 because the server raises smaller windows), temperature 0, the JSON schema as `format` and `think: false`. Model output is data: it is parsed with the schema and a mismatch is `SchemaViolation`, which carries the schema error and never the output.

| Situation | Error |
| --- | --- |
| Server unreachable or timed out | `ProviderUnavailable` |
| HTTP 429 | `RateLimited` (with `Retry-After` if sent) |
| Any other HTTP status, including a redirect (never followed) | `ProviderUnavailable` with the status |
| Output cut off or not matching the schema | `SchemaViolation` |
| Prompt too long, or truncation detected | `ContextTruncated` |

Local setup: install [Ollama](https://ollama.com), then pull a model. Approved for local runs are `qwen3.5:4b` and `qwen3.5:9b`. CI and the live tests use the tiny `qwen3.5:0.8b`, which proves the plumbing and the guard but says nothing about quality.
```bash
ollama pull qwen3.5:4b
```

## The budget guard
Code is `src/cypress_creek/providers/budget.py`. A run has four limits, and a call that could pass any of them is refused before it is sent.

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_input_tokens` | 500000 | Input tokens for the whole run |
| `max_output_tokens` | 100000 | Output tokens for the whole run |
| `max_requests` | 500 | Number of calls |
| `max_usd` | 2.0 | Dollars, from the backend's `cost_per_mtok`. Local backends cost nothing, so only the three token and request caps bite there |

- `BudgetTracker(budget, cost_per_mtok)` keeps the totals. `check_before(input_tokens, max_output_tokens)` raises `BudgetExceeded` when the estimate plus the output cap (the worst case) would pass a limit. `record(usage)` adds what the server reported and never raises, so real usage above an estimate blocks the next call. The guard fails closed.
- `BudgetedProvider(inner, tracker)` wraps any provider. Each call is estimated with `estimate_input_tokens` (the same estimate the Ollama pre-flight check uses), checked, sent, then recorded. A call that fails is not recorded.
- `BudgetExceeded` carries `limit_name` (`input_tokens`, `output_tokens`, `requests` or `usd`), `limit` and `would_reach`. It is never retried.
- `dry_run_estimate(provider, budget, plan)` takes a list of `PlannedCall` (system text, data block, `output_schema`, output cap) and returns a `CostEstimate` with the projected input tokens, output tokens (every call at its cap), requests and dollars. A plan that does not fit raises `BudgetExceeded`, with no call made.
- The limits are optional settings, see Configuration. `budget_from_settings(settings)` turns them into a `Budget`, with the defaults above for anything unset.

## Configuration
Code is `src/cypress_creek/config/settings.py`. The format is TOML, see [ADR 0007](adr/0007-provider-config-toml-and-loopback.md). Copy this to `config/provider.toml` (or point `CYPRESS_CREEK_CONFIG` at another file):
```toml
provider = "ollama"
model = "llama3.1"
base_url = "http://localhost:11434"
# allow_remote = true              # required for any host that is not loopback
# api_key_env = "OPENAI_API_KEY"   # the NAME of an environment variable, never the key  # pragma: allowlist secret
# request_timeout_seconds = 120
# connect_timeout_seconds = 5
# context_tokens = 8192            # the window sent as num_ctx, at least 2048 for ollama
# max_input_tokens = 500000        # budget limits for a run, see the budget guard
# max_output_tokens = 100000
# max_requests = 500
# max_usd = 2.0
```
- `provider` and `model` are required. The other fields are optional.
- Any field can be overridden by `CYPRESS_CREEK_<FIELD>`, for example `CYPRESS_CREEK_MODEL=qwen3`. Blank values are ignored.
- The loopback rule: a `base_url` must be http or https. A `base_url` with a user name or password in it is rejected. A host that is not `localhost` or a loopback address (`127.0.0.1`, `::1`) is rejected unless `allow_remote = true`. This keeps a posting and your facts from going to a remote host by accident.
- Keys: the file holds `api_key_env`, and `resolve_api_key(settings)` reads that variable when an adapter needs it. A missing variable is an error that names the variable, never a value.
- Every failure is a `ConfigError`. Messages carry field names and rules only, so a key pasted into a URL is not echoed back.

`get_provider(settings)` (in `providers/factory.py`) finds the adapter registered under `settings.provider`. An unknown name raises `UnknownProvider`, a `ConfigError` listing the known names. `ollama` is the only adapter registered so far.

Known limits: the loopback check reads the URL text, so a name that resolves elsewhere or a redirect is not caught (adapters must not follow redirects off the configured host). A backend with a built in remote default URL must demand `allow_remote` itself, because an empty `base_url` passes.

## Try it locally
```bash
uv run python -c "from cypress_creek.providers import ProviderUnavailable; print(ProviderUnavailable('openai', 'bad key sk-123', secrets=['sk-123']))"
uv run python -c "from cypress_creek.providers import RateLimited, call_with_retry; outcomes = [RateLimited(retry_after_seconds=0.1)]; call = lambda feedback: (_ for _ in ()).throw(outcomes.pop()) if outcomes else 'done'; print(call_with_retry(call))"
```
The first prints `openai unavailable: bad key [redacted]`. The second waits a tenth of a second after one rate limit and prints `done`.

Load the config and see the loopback rule (no file needed, the environment is enough):
```bash
CYPRESS_CREEK_PROVIDER=ollama CYPRESS_CREEK_MODEL=llama3.1 uv run python -c "from cypress_creek.config import load_settings; print(load_settings())"
CYPRESS_CREEK_PROVIDER=ollama CYPRESS_CREEK_MODEL=m CYPRESS_CREEK_BASE_URL=https://api.example.com uv run python -c "from cypress_creek.config import load_settings; load_settings()"
```
The first prints the settings. The second fails with a `ConfigError` telling you to set `allow_remote`. In Windows PowerShell set each variable first, for example `$env:CYPRESS_CREEK_PROVIDER = "ollama"`, then run the `uv run python` part.

Run the Ollama adapter against a real server (start `ollama serve` and run `ollama pull qwen3.5:0.8b` first):
```bash
CYPRESS_CREEK_PROVIDER=ollama CYPRESS_CREEK_MODEL=qwen3.5:0.8b uv run python -c "
from pydantic import BaseModel
from cypress_creek.config import load_settings
from cypress_creek.providers import get_provider

class Greeting(BaseModel):
    text: str

result = get_provider(load_settings()).complete_structured('Reply with a short greeting.', 'Say hi', Greeting, 100)
print(result.parsed, result.usage)
"
```
It prints a greeting and the token usage. Change `'Say hi'` to `'word ' * 6000` and it raises `ContextTruncated` before any request is made. The live tests run the same checks, including a real overflow, and fail (never skip) if Ollama or the model is missing:
```bash
uv run pytest tests/integration -m live -q
```
The `live` GitHub Actions workflow (`.github/workflows/live.yml`) does this on a schedule and on demand with a fresh Ollama and `qwen3.5:0.8b`.

Print the projected cost of a plan (three small calls) with the budget from the same settings. No call is made, so no server needs to be running:
```bash
CYPRESS_CREEK_PROVIDER=ollama CYPRESS_CREEK_MODEL=qwen3.5:0.8b uv run python -c "
from pydantic import BaseModel
from cypress_creek.config import load_settings
from cypress_creek.providers import get_provider
from cypress_creek.providers.budget import PlannedCall, budget_from_settings, dry_run_estimate

class Greeting(BaseModel):
    text: str

settings = load_settings()
call = PlannedCall(system='Reply with a short greeting.', data_block='Say hi', output_schema=Greeting, max_output_tokens=100)
print(dry_run_estimate(get_provider(settings), budget_from_settings(settings), [call] * 3))
"
```
It prints `input_tokens=159 output_tokens=300 requests=3 usd=0.0`. Set `CYPRESS_CREEK_MAX_REQUESTS=2` in front of it and it fails with `BudgetExceeded: requests limit 2 would be exceeded, reaching 3`.
