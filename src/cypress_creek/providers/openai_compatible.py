# ABOUTME: The openai_compatible adapter: chat completions with a strict JSON schema reply format.
# ABOUTME: One adapter serves OpenAI and LM Studio, chosen by base_url. Hosted use needs a key.
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from cypress_creek.config import (
    ConfigError,
    ProviderSettings,
    describe_validation_error,
    is_loopback_url,
    resolve_api_key,
)
from cypress_creek.providers.base import (
    Capabilities,
    CostPerMtok,
    StructuredResult,
    Usage,
    estimate_input_tokens,
)
from cypress_creek.providers.errors import (
    ContextTruncated,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
)
from cypress_creek.providers.factory import REGISTRY
from cypress_creek.providers.ollama import estimate_tokens
from cypress_creek.providers.strict_schema import strict_schema

PROVIDER = "openai_compatible"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
CHARS_PER_TOKEN = 3
ERROR_BODY_LIMIT = 200

# Phrases servers use when a prompt does not fit. The code is OpenAI's, the others are the
# wording of the messages a local server sends, matched on lower case text.
CONTEXT_ERROR_MARKERS = (
    "context_length_exceeded",
    "context length",
    "context window",
    "context overflow",
    "context the overflows",
)


def check_pre_flight(input_tokens: int, max_output_tokens: int, context_tokens: int) -> None:
    """Refuse before calling when the input plus the output cap cannot fit the declared window."""
    needed = input_tokens + max_output_tokens
    if needed > context_tokens:
        raise ContextTruncated(needed, context_tokens)


def check_response_status(
    response: httpx.Response, context_tokens: int, secrets: Sequence[str]
) -> None:
    """Map a failed HTTP status to its typed error. Redirects are not followed, so they fail."""
    if response.status_code == 200:
        return
    if response.status_code == 429:
        raise RateLimited(_retry_after(response))
    text = response.text[:ERROR_BODY_LIMIT]
    if response.status_code == 400 and any(
        marker in response.text.lower() for marker in CONTEXT_ERROR_MARKERS
    ):
        raise ContextTruncated(context_tokens, context_tokens, detected_after_call=True)
    raise ProviderUnavailable(PROVIDER, f"HTTP {response.status_code}: {text}", secrets)


def read_completion[T: BaseModel](
    body: dict[str, Any], schema: type[T], context_tokens: int, secrets: Sequence[str]
) -> StructuredResult[T]:
    """Turn a chat completions reply into a result. The reply is untrusted until it parses."""
    choice = _first_choice(body, secrets)
    usage = _usage(body, secrets)
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProviderUnavailable(PROVIDER, "response has no message", secrets)
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        raise Refusal(PROVIDER)
    if usage.input_tokens >= context_tokens:
        raise ContextTruncated(usage.input_tokens, context_tokens, detected_after_call=True)
    content = message.get("content")
    if choice.get("finish_reason") == "length":
        raise SchemaViolation(schema.__name__, "output was cut off by the token cap", secrets)
    if not isinstance(content, str):
        raise ProviderUnavailable(PROVIDER, "response has no message content", secrets)
    try:
        parsed = schema.model_validate_json(content)
    except ValidationError as error:
        raise SchemaViolation(schema.__name__, describe_validation_error(error), secrets) from None
    return StructuredResult(parsed=parsed, raw_text=content, usage=usage)


def _first_choice(body: dict[str, Any], secrets: Sequence[str]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderUnavailable(PROVIDER, "response has no choices", secrets)
    return choices[0]


def _count(usage: object, field: str, secrets: Sequence[str]) -> int:
    value = usage.get(field) if isinstance(usage, dict) else None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderUnavailable(PROVIDER, f"response has no usable usage.{field}", secrets)
    return value


def _usage(body: dict[str, Any], secrets: Sequence[str]) -> Usage:
    usage = body.get("usage")
    return Usage(
        input_tokens=_count(usage, "prompt_tokens", secrets),
        output_tokens=_count(usage, "completion_tokens", secrets),
    )


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


class OpenAICompatibleProvider:
    def __init__(
        self,
        settings: ProviderSettings,
        environ: Mapping[str, str] | None = None,
        chars_per_token: int = CHARS_PER_TOKEN,
    ) -> None:
        self._settings = settings
        self._chars_per_token = chars_per_token
        self._base_url = (settings.base_url or DEFAULT_BASE_URL).rstrip("/")
        self._local = is_loopback_url(self._base_url)
        self._key: str | None = None
        if not self._local:
            self._key = self._remote_key(settings, environ)
        elif settings.api_key_env is not None:
            self._key = resolve_api_key(settings, environ)
        self._cost = self._cost_per_mtok(settings)

    def _remote_key(self, settings: ProviderSettings, environ: Mapping[str, str] | None) -> str:
        if not settings.allow_remote:
            raise ConfigError(f"{PROVIDER} sends data to a remote host; set allow_remote = true")
        key = resolve_api_key(settings, environ)
        if key is None:
            raise ConfigError(f"{PROVIDER} needs api_key_env for a remote host")
        return key

    def _cost_per_mtok(self, settings: ProviderSettings) -> CostPerMtok:
        if self._local:
            return CostPerMtok(input=0, output=0)
        if settings.cost_input_per_mtok is None or settings.cost_output_per_mtok is None:
            raise ConfigError(
                "a remote host needs cost_input_per_mtok and cost_output_per_mtok, "
                "so the budget guard can price calls"
            )
        return CostPerMtok(input=settings.cost_input_per_mtok, output=settings.cost_output_per_mtok)

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            context_tokens=self._settings.context_tokens,
            # Hosted strict mode is documented. A local server is unproven until verified for the
            # loaded model, so the pipeline validates harder.
            strict_schema=not self._local,
            local=self._local,
            cost_per_mtok=self._cost,
        )

    def count_tokens_estimate(self, text: str) -> int:
        return estimate_tokens(text, self._chars_per_token)

    def request_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._key is not None:
            headers["Authorization"] = f"Bearer {self._key}"
        return headers

    def build_request[T: BaseModel](
        self, system: str, data_block: str, schema: type[T], max_output_tokens: int
    ) -> dict[str, Any]:
        """The request body as a plain value. System text and the untrusted block stay apart."""
        request: dict[str, Any] = {
            "model": self._settings.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": data_block},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": strict_schema(schema, require_all=True),
                },
            },
        }
        if self._local:
            request["max_tokens"] = max_output_tokens
            request["temperature"] = 0
        else:
            request["max_completion_tokens"] = max_output_tokens
        return request

    def complete_structured[T: BaseModel](
        self, system: str, data_block: str, schema: type[T], max_output_tokens: int
    ) -> StructuredResult[T]:
        context = self._settings.context_tokens
        input_tokens = estimate_input_tokens(self, system, data_block, schema)
        check_pre_flight(input_tokens, max_output_tokens, context)
        secrets = [self._key] if self._key else []
        observed_usage: Usage | None = None
        try:
            body = self._post(self.build_request(system, data_block, schema, max_output_tokens))
            observed_usage = _observed_usage(body)
            return read_completion(body, schema, context, secrets)
        except ProviderError as error:
            error.mark_attempt(observed_usage)
            raise

    def _post(self, request: dict[str, Any]) -> dict[str, Any]:
        secrets = [self._key] if self._key else []
        timeout = httpx.Timeout(
            self._settings.request_timeout_seconds, connect=self._settings.connect_timeout_seconds
        )
        try:
            response = httpx.post(
                self.endpoint, json=request, headers=self.request_headers(), timeout=timeout
            )
        except httpx.HTTPError as error:
            raise ProviderUnavailable(
                PROVIDER, f"{type(error).__name__} at {self._base_url}", secrets
            ) from None
        check_response_status(response, self._settings.context_tokens, secrets)
        try:
            body = response.json()
        except ValueError:
            raise ProviderUnavailable(PROVIDER, "response is not JSON", secrets) from None
        if not isinstance(body, dict):
            raise ProviderUnavailable(PROVIDER, "response is not a JSON object", secrets)
        return body


def _observed_usage(body: dict[str, Any]) -> Usage | None:
    """Usage the server reported, when both counts are usable. Used to charge a failed call."""
    try:
        return _usage(body, [])
    except ProviderUnavailable:
        return None


REGISTRY.register(PROVIDER, OpenAICompatibleProvider)
