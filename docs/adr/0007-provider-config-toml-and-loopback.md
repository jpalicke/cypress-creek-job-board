# ADR 0007: Provider config is TOML plus environment overrides, remote hosts are opt in

Status: accepted (Joe P, card C1b)

## Decision
- Backend settings live in a TOML file read with the standard library `tomllib`. The default path is `config/provider.toml`, or the file named by `CYPRESS_CREEK_CONFIG`, or an explicit path argument.
- Each field can be overridden by `CYPRESS_CREEK_<FIELD>` (for example `CYPRESS_CREEK_MODEL`). A blank value is ignored. There is no `pydantic-settings` dependency.
- A file named explicitly must exist. The default file may be absent when the environment sets every required field.
- A `base_url` must be http or https with a host. A `base_url` with credentials in it is rejected, so a key cannot be stored in the URL. If the host is not loopback (`localhost`, or any address `ipaddress` calls loopback, so `127.0.0.1` and `::1`), the config is rejected unless `allow_remote = true`.
- API keys are never in the file. The file holds `api_key_env`, the name of an environment variable, and `resolve_api_key` reads it at the moment of use.
- Every config failure is a `ConfigError`. Its message is built from field names and rule text only, never from submitted values, so a key pasted into a URL cannot leak through an error.
- `get_provider(settings)` looks the provider name up in a `ProviderRegistry`. An unknown name raises `UnknownProvider`, a `ConfigError` that lists the known names. Adapters register themselves in their own cards.

## Why
TOML is in the standard library, reads well for settings and keeps config separate from the YAML data (fact bank, weights). A handful of explicit environment lines is simpler than a settings library. Defaulting to loopback means a typo cannot send a posting and facts to a remote host: going remote is a visible, deliberate line in the file (threats T14 and T17). Keeping keys out of the file and out of error text means there is nothing to commit or log by accident.

## Limits
- The check is on the URL text. A loopback name that resolves elsewhere (for example a hosts file entry) is not detected, and neither is a redirect to a remote host. Adapters must not follow redirects off the configured host.
- An adapter whose backend has a built in remote default URL must demand `allow_remote` itself, because `base_url = None` passes the check.
