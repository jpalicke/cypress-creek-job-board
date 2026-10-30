# Providers

The provider layer is how the pipeline talks to a model. Every backend (local or hosted) implements one interface, so the pipeline and the eval harness never know which one they use. Code is `src/cypress_creek/providers/`. This page covers the interface, the typed errors, the retry policy, the config that selects a backend, the Ollama adapter, the Anthropic adapter and the `openai_compatible` adapter. The other adapters arrive in later cards (see the issue board).

## The interface
`Provider` is a `typing.Protocol` in `providers/base.py`:
- `complete_structured(system, data_block, schema, max_output_tokens) -> StructuredResult[T]`. `schema` is a pydantic model class and `T` is that class.
- `count_tokens_estimate(text) -> int`.
- `capabilities`: a `Capabilities` with `context_tokens`, `strict_schema`, `local` and `cost_per_mtok` (a `CostPerMtok` of dollars per million input and output tokens, zero for local backends).

`system` and `data_block` are separate arguments on purpose. `system` is trusted and static. `data_block` is untrusted posting text, wrapped by the prompt builder in a random per request boundary. Keeping them apart means an adapter cannot merge them by accident. The fact bank is a separate trusted block, added by the prompt builder card.

`StructuredResult` carries `parsed` (the validated model), `raw_text` and `usage` (`Usage` with input and output tokens). The parsed model is still model output: nothing in it is trusted until the validators pass it.

## Typed errors
All in `providers/errors.py`, all subclasses of `ProviderError`. Callers branch on the class and never on the message text.
An error also carries `request_attempted` and nullable `usage`, so a caller can distinguish a
preflight refusal from a request that reached the adapter. The adapter attaches usage only when
the backend reported both token counts. Neither field is inferred from the error message.

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
1. **Before the call.** It estimates tokens for the system text, the data block and the schema, adds the output cap, and raises `ContextTruncated` without calling the model if the total exceeds `context_tokens`. The estimate is the character count divided by 3, rounded up. It can undercount text that tokenizes densely, including CJK text.
2. **After the call.** It compares the `prompt_eval_count` the server reports with the estimate. A count in the measured half-window truncation band raises `ContextTruncated` regardless of the estimate. A count near the full window also raises it when the estimate was below that range. A response with no usage counts is an error.

Every request sets `num_ctx` from `context_tokens` (default 8192, minimum 2048 because the server raises smaller windows), temperature 0, the JSON schema as `format` and `think: false`. The 50,000-character posting cap limits normalized input size; it does not guarantee that a posting fits the configured model context. Increase `context_tokens` when the model and machine can support a larger window. Model output is data: it is parsed with the schema and a mismatch is `SchemaViolation`, which carries the schema error and never the output.

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

## The Anthropic adapter
Code is `src/cypress_creek/providers/anthropic.py`, registered as provider `anthropic`. It calls the Messages API (`POST /v1/messages`) with native structured output and defaults to the model `claude-sonnet-5-5`. Decisions are in [ADR 0025](adr/0025-anthropic-native-structured-output.md).

**Proven against the live API.** On 2026-10-30 Joe P ran `uv run pytest tests/integration/test_anthropic_live.py -q` with a real key and both tests passed (the wrong-key 401 and the real structured call, which returned a conforming object with reported usage). The model id and usage numbers were not recorded; see [issue #129](https://github.com/jpalicke/cypress-creek-job-board/issues/129).

- **Hosted rules.** It needs `allow_remote = true`, an `api_key_env` naming the variable that holds the key (never the key itself), and an https URL for any remote `base_url`. The key is sent only in the `x-api-key` header, redirects are not followed, and every error scrubs it. Facts marked `local_only` are left out of the prompt for any backend whose `local` capability is false, so they never reach the request body.
- **Request.** The trusted system text is the top level `system` field. The untrusted data block (the posting inside its boundary, then any trusted facts) is the single user message. The schema goes in `output_config.format` after the adapter closes every object and drops the keywords the grammar rejects (the pydantic model still validates the answer). No tools are offered.
- **Answer.** Only `text` blocks are read. `refusal` is the typed `Refusal`. An answer cut off at `max_tokens` or not matching the schema is a `SchemaViolation` (retried once with only the error text). Usage is read from the response, including cache token fields, and a response without complete counts is an error.

| Situation | Error |
| --- | --- |
| Server unreachable or timed out | `ProviderUnavailable` |
| HTTP 429 or 529 | `RateLimited` (with `retry-after` if sent) |
| HTTP 429 for the monthly spend cap | `ProviderUnavailable`, not retried |
| Any other non-200 status, including a redirect | `ProviderUnavailable` with the status, error type and `request-id` |
| `stop_reason` of `refusal` | `Refusal` |
| Cut off at `max_tokens`, or not matching the schema | `SchemaViolation` |
| Any other `stop_reason`, or missing text or usage | `ProviderUnavailable` |
| Prompt plus output cap over `context_tokens` | `ContextTruncated`, before any request |

Setup: create a key in the Claude Console, then put its name in the config and the key itself in your shell (or a gitignored `.env` that you load into the shell). Never commit a key.
```toml
provider = "anthropic"
model = "claude-sonnet-5-5"
allow_remote = true
api_key_env = "ANTHROPIC_API_KEY"   # pragma: allowlist secret
# context_tokens = 1000000          # default for this adapter, not 8192
# input_usd_per_mtok = 2.0          # defaults exist for claude-sonnet-5-5 (2 and 10),
# output_usd_per_mtok = 10.0        # claude-opus-5-5 (4 and 20) and claude-fable-5-1 (10 and 50)
```
Another model needs both prices set, or the adapter refuses to start. Only hosted adapters read `input_usd_per_mtok` and `output_usd_per_mtok`; the Ollama adapter ignores them and costs nothing. Thinking is left at the model default and its tokens count against the output cap, so give structured calls a generous `max_output_tokens`.

Run it once against the real API (costs a fraction of a cent):
```bash
export ANTHROPIC_API_KEY=...   # your key
CYPRESS_CREEK_PROVIDER=anthropic CYPRESS_CREEK_MODEL=claude-sonnet-5-5 CYPRESS_CREEK_ALLOW_REMOTE=true CYPRESS_CREEK_API_KEY_ENV=ANTHROPIC_API_KEY uv run python -c "
from pydantic import BaseModel
from cypress_creek.config import load_settings
from cypress_creek.providers import get_provider

class Greeting(BaseModel):
    text: str

result = get_provider(load_settings()).complete_structured('Reply with a short greeting.', 'Say hi', Greeting, 2000)
print(result.parsed, result.usage)
"
```
It prints a greeting and the real token usage. Without the variable it fails with `environment variable ANTHROPIC_API_KEY is not set` and makes no request. The live tests are `uv run pytest tests/integration/test_anthropic_live.py -q`. They fail, never skip, when the key is missing (the real call test), and the wrong key test needs only the internet.

## The openai_compatible adapter (OpenAI and LM Studio)
Code is `src/cypress_creek/providers/openai_compatible.py`, registered as provider `openai_compatible`. One adapter serves OpenAI and LM Studio, chosen by `base_url`. The live OpenAI call passed once on 2026-10-30 and both LM Studio live tests passed the same day (see ADR 0027). Decisions, the model pick and what is still unverified are in [ADR 0027](adr/0027-openai-compatible-adapter-and-model-pick.md).

- It calls `POST <base_url>/chat/completions` with the system text and the untrusted data block as two separate messages (`system`, then `user`). The fact bank, when a stage shows facts, travels after the data block inside the user message, as the prompt builder lays it out.
- Output: `response_format` is `json_schema` with `strict: true`. The schema is the pydantic model's, with every property required and unsupported keywords (`minLength`, `maximum`, defaults and the like) removed by `providers/strict_schema.py`. The reply is parsed with the original model, so the removed constraints are still checked.
- Where it sends data: with no `base_url` the adapter uses `https://api.openai.com/v1`, which needs `allow_remote = true` (and an https URL, because the key travels in a header), an `api_key_env` naming a set variable and both price settings (`input_usd_per_mtok`, `output_usd_per_mtok`, dollars per million tokens). A loopback `base_url` (LM Studio) needs none of these and costs zero. The key goes only in the `Authorization` header and is scrubbed from every error.
- `local_only` facts: the adapter reports `local = false` for any host that is not loopback, and `build_prompt` leaves `local_only` facts out of a prompt for a non local backend (validator V6 checks it again on the report). A component test builds a hosted request from a real prompt and shows the fact is absent.
- Temperature: hosted calls send none. `gpt-6-luna` rejects `temperature: 0` (HTTP 400, "Only the default (1) value is supported", recorded 2026-10-30), so a hosted row is never temperature pinned; see ADR 0027.
- Capabilities: `context_tokens` is the setting (default 8192; set it to the window the model is loaded with, or the hosted model's window). `strict_schema` is true for a remote host and false for a loopback one until LM Studio is verified.

| Situation | Error |
| --- | --- |
| Server unreachable or timed out, or any other HTTP status | `ProviderUnavailable` (the key is scrubbed) |
| HTTP 429 | `RateLimited` (with `Retry-After` if sent) |
| HTTP 400 naming a context length problem (carries the estimate, not a server count), or a reported prompt count at or above the window | `ContextTruncated` |
| Estimate plus output cap over `context_tokens` | `ContextTruncated`, before any request |
| Output cut off by the cap, or not matching the schema | `SchemaViolation` |
| A `refusal` field or a `content_filter` finish | `Refusal` |
| Reply with no choices, no content or unusable usage counts | `ProviderUnavailable` |

The two hosted adapters differ on prices on purpose: the Anthropic adapter has built in prices for three known models and lets the settings override them, while this one has no price table and refuses a remote host unless both prices are set. Hosted OpenAI calls send no temperature, so the OpenAI rows of a published comparison are not temperature pinned (see the ADR).

Config for OpenAI (the model and prices are settings; confirm them against the models page first, see the ADR):
```toml
provider = "openai_compatible"
model = "gpt-6-luna"
allow_remote = true
api_key_env = "OPENAI_API_KEY"   # the NAME of the variable  # pragma: allowlist secret
context_tokens = 32768
input_usd_per_mtok = 0.10
output_usd_per_mtok = 0.50
```
Config for LM Studio (start its local server and load a model first; the port is LM Studio's default):
```toml
provider = "openai_compatible"
model = "<the identifier LM Studio shows for the loaded model>"
base_url = "http://localhost:1234/v1"
context_tokens = 4096            # the context length the model was loaded with
```

### LM Studio findings (partly verified)
The command to run, what to record and the other open sign-offs for this adapter are in [issue #130](https://github.com/jpalicke/cypress-creek-job-board/issues/130).

On 2026-10-30 Joe P ran both `live_lmstudio` tests against his LM Studio and they passed (`2 passed`). The run itself recorded no server wording; the version, model and loaded context length were reported afterwards. The rows below say only what the passing tests establish. Everything else is still not known.

| Question | Finding |
| --- | --- |
| LM Studio version and model tested | LM Studio 0.4.17 (Build 4), model `gemma-4-e4b` (the identifier LM Studio lists carries a vendor prefix), loaded with a context length of 8192, the same value passed to the tests as `CYPRESS_CREEK_LMSTUDIO_CONTEXT` (reported by Joe P after the run) |
| Is the loaded context length exposed by the model listing, or must config supply it? | not recorded (the adapter reads `context_tokens` from config; the test config supplied it). The model was loaded with 8192 and both the load and the tests used 8192 |
| Is `response_format` `json_schema` honored for the model? | not established: a conforming reply passes either way because every reply is validated against the schema; `strict_schema` stays false |
| How is a prompt over the loaded context reported? | LM Studio 0.4.17 answers with an error body whose `error` is a plain string: "The number of tokens to keep from the initial prompt is greater than the context length (n_keep: 20015>= n_ctx: 8192). Try to load the model with a larger context length, or provide a shorter input." (recorded by Joe P on 2026-10-30; the HTTP status was not shown, the adapter treats a 400 as the overflow). The existing `context length` marker matches it, and a component test pins the recorded text. The other markers are still guesses |

## The budget guard
Code is `src/cypress_creek/providers/budget.py`. A run has four limits, and a call that could pass any of them is refused before it is sent.

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_input_tokens` | 500000 | Input tokens for the whole run |
| `max_output_tokens` | 100000 | Output tokens for the whole run |
| `max_requests` | 500 | Number of calls |
| `max_usd` | 2.0 | Dollars, from the backend's `cost_per_mtok`. Local backends cost nothing, so only the three token and request caps bite there |

- `BudgetTracker(budget, cost_per_mtok)` keeps the totals. `check_before(input_tokens, max_output_tokens)` raises `BudgetExceeded` when the estimate plus the output cap (the worst case) would pass a limit. `record(usage)` adds reported usage. `record_attempt(usage)` also counts a failed request and adds its reported usage when known. Unknown usage blocks the next call because the remaining budget cannot be proven. Both methods leave a later overrun to `check_before`, so an attempted call is never erased.
- `BudgetedProvider(inner, tracker)` wraps any provider. Each call is estimated with `estimate_input_tokens` (the same estimate the Ollama pre-flight check uses), checked, then sent. Successful and attempted failed requests count against the request cap. A preflight or budget refusal does not count as a request.
- `BudgetExceeded` carries `limit_name` (`input_tokens`, `output_tokens`, `requests`, `usd` or `unknown_usage`), `limit` and `would_reach`. It is never retried.
- `dry_run_estimate(provider, budget, plan)` takes a list of `PlannedCall` (system text, data block, `output_schema`, output cap) and returns a `CostEstimate` with the projected input tokens, output tokens (every call at its cap), requests and dollars. A plan that does not fit raises `BudgetExceeded`, with no call made.
- The limits are optional settings, see Configuration. `budget_from_settings(settings)` turns them into a `Budget`, with the defaults above for anything unset.

## Configuration
Code is `src/cypress_creek/config/settings.py`. The format is TOML, see [ADR 0007](adr/0007-provider-config-toml-and-loopback.md). Copy this to `config/provider.toml` (or point `CYPRESS_CREEK_CONFIG` at another file):
```toml
provider = "ollama"
model = "llama3.1"
base_url = "http://localhost:11434"
# allow_remote = true              # required for any host that is not loopback
# api_key_env = "ANTHROPIC_API_KEY"   # the NAME of an environment variable, never the key  # pragma: allowlist secret
# request_timeout_seconds = 120
# connect_timeout_seconds = 5
# context_tokens = 8192            # the window sent as num_ctx, at least 2048 for ollama
# max_input_tokens = 500000        # budget limits for a run, see the budget guard
# max_output_tokens = 100000
# max_requests = 500
# max_usd = 2.0
# input_usd_per_mtok = 2.0       # dollars per million tokens, for a model with no built in price
# output_usd_per_mtok = 10.0       # required for a remote host such as OpenAI
```
- `provider` and `model` are required. The other fields are optional.
- Any field can be overridden by `CYPRESS_CREEK_<FIELD>`, for example `CYPRESS_CREEK_MODEL=qwen3`. Blank values are ignored.
- The loopback rule: a `base_url` must be http or https. A `base_url` with a user name or password in it is rejected. A host that is not `localhost` or a loopback address (`127.0.0.1`, `::1`) is rejected unless `allow_remote = true`. This keeps a posting and your facts from going to a remote host by accident.
- Keys: the file holds `api_key_env`, and `resolve_api_key(settings)` reads that variable when an adapter needs it. A missing variable is an error that names the variable, never a value.
- Every failure is a `ConfigError`. Messages carry field names and rules only, so a key pasted into a URL is not echoed back.

`get_provider(settings)` (in `providers/factory.py`) finds the adapter registered under `settings.provider`. An unknown name raises `UnknownProvider`, a `ConfigError` listing the known names. `ollama`, `anthropic` and `openai_compatible` are registered.

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
uv run pytest tests/e2e tests/integration -m "live and not needs_network and not live_openai and not live_lmstudio" -q
```
The `live` GitHub Actions workflow (`.github/workflows/live.yml`) does this on a schedule and on demand with a fresh Ollama and `qwen3.5:0.8b`. It selects `live and not needs_network and not live_openai and not live_lmstudio` in `tests/e2e` and `tests/integration`, so the Anthropic live test, which needs a key and spends money, never runs there. Credentialed or desktop-only live tests that are not `needs_network` must use their own marker (as the OpenAI and LM Studio tests do) and be added to this selector's exclusions.

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

Build an `openai_compatible` request without sending it (no server or key needed, because a loopback `base_url` is local):
```bash
CYPRESS_CREEK_PROVIDER=openai_compatible CYPRESS_CREEK_MODEL=local-model CYPRESS_CREEK_BASE_URL=http://localhost:1234/v1 uv run python -c "
import json
from pydantic import BaseModel
from cypress_creek.config import load_settings
from cypress_creek.providers import get_provider

class Greeting(BaseModel):
    text: str

print(json.dumps(get_provider(load_settings()).build_request('Reply with a short greeting.', 'Say hi', Greeting, 100), indent=2))
"
```
It prints the request: a `system` message and a `user` message, a strict `json_schema` response format, `max_tokens` 100 and temperature 0. Leave out `CYPRESS_CREEK_BASE_URL` and the adapter refuses with a `ConfigError` saying to set `allow_remote = true`, because the default host is OpenAI.

The adapter's HTTP path (URL, headers, body, status mapping, reply parsing) is tested against a real loopback server in `tests/component/test_openai_http.py`, and `tests/e2e/test_openai_compatible_process.py` runs the factory and a call in a child process against the same kind of server: `uv run pytest tests/component/test_openai_http.py tests/e2e/test_openai_compatible_process.py -q --no-cov`. These prove the plumbing, not what OpenAI or LM Studio do.

The credentialed live tests have their own markers, so `-m live` (and the `live` workflow) never run them:

| Marker | Test file | How to run |
| --- | --- | --- |
| `live_lmstudio` | `tests/integration/test_openai_compatible_lmstudio.py` | By hand only. LM Studio is a desktop app, so CI cannot run it. |
| `live_openai` (and `needs_network`) | `tests/integration/test_openai_live.py` | By hand with `OPENAI_API_KEY` set, or the manual `openai-live` workflow with a repository secret of that name. |

```bash
# LM Studio: start its local server, load a model, then
CYPRESS_CREEK_LMSTUDIO_MODEL="<loaded model identifier>" CYPRESS_CREEK_LMSTUDIO_CONTEXT=4096 uv run pytest tests/integration -m live_lmstudio -q
# OpenAI: put the key in the environment or a gitignored .env loaded into your shell
OPENAI_API_KEY="<your key>" uv run pytest tests/integration -m live_openai -q  # pragma: allowlist secret
```
Both fail, never skip, when the server or the key is missing. `CYPRESS_CREEK_LMSTUDIO_BASE_URL` (default `http://localhost:1234/v1`) and `CYPRESS_CREEK_OPENAI_MODEL` (default `gpt-6-luna`) override the targets. After the LM Studio run, fill in the findings table above.
