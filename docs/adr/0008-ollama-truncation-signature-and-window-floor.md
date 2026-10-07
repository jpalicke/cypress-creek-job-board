# ADR 0008: How the Ollama adapter detects silent truncation

Status: accepted (Joe P, card C2)

## Decision
- The adapter calls the native `/api/chat` endpoint and sets `options.num_ctx` on every request. `context_tokens` in the settings is that value. Temperature is 0, `format` carries the JSON schema and `think` is false.
- Pre-flight: the estimate (characters divided by 3, rounded up) of the system text, the data block and the schema text, plus the output cap, must fit `num_ctx`. Otherwise `ContextTruncated` is raised and no request is made.
- Post-flight: a `prompt_eval_count` from half the window to half the window plus 16 tokens is treated as truncation regardless of the estimate. A count at or above 95% of the window is also treated as truncation when the estimate was below 95%. A response without usage counts is an error, because it cannot be checked.
- `context_tokens` below 2048 is a config error for this adapter.

## Why
Measured against Ollama 0.34.4 with `qwen3.5:0.8b`: a prompt that overflows the window is cut to its first few tokens plus about half the window, and `prompt_eval_count` reports that cut length, not the full input size. At `num_ctx` 2048 it reported 1026, at 4096 it reported 2050, and at 32768 it reported 16386 for a 50,000-character CJK input. The spec's rule, a count near `num_ctx`, would not have fired. The same server raises any `num_ctx` below 2048 to 2048, so the half window band is only meaningful from 2048 up. The server also keeps no stale counts: repeated identical requests report the same number.

`think` is false because `qwen3.5` models otherwise spend the whole output cap on reasoning before the constrained JSON starts, and the content comes back empty.

## Limits
- The half window band is a measurement of one server version, not a documented contract. The `live` CI job runs the overflow test against whatever version it installs and fails loudly if the signature changes.
- A prompt that really measures between half the window and half the window plus 16 tokens is refused, even if the estimate is higher. The reported count cannot distinguish a valid prompt in this band from a truncated one, so the adapter fails closed.
- The estimate can under count for text that tokenizes poorly, such as CJK text. The post-flight check exists for that case.
