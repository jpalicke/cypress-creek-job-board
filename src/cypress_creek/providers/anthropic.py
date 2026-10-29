# ABOUTME: The Anthropic adapter, built on the Messages API with native JSON schema output.
# ABOUTME: Hosted rules: allow_remote, https, key from the environment only and never in an error.
import copy
import math
import os
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from cypress_creek.config import (
    ConfigError,
    ProviderSettings,
    describe_validation_error,
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

PROVIDER = "anthropic"
DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
MESSAGES_PATH = "/v1/messages"

# The documented window of the current models. A configured `context_tokens` replaces it, because
# the setting's own default is the small local default and cannot be told apart from a choice
# unless it was set.
DEFAULT_CONTEXT_TOKENS = 1_000_000

# Dollars per million input and output tokens, from the models overview. A model not listed here
# needs `input_usd_per_mtok` and `output_usd_per_mtok` in the settings, so a budget never runs on
# a guessed price.
KNOWN_PRICES = {
    "claude-sonnet-5-5": CostPerMtok(input=2.0, output=10.0),
    "claude-opus-5-5": CostPerMtok(input=4.0, output=20.0),
    "claude-fable-5-1": CostPerMtok(input=10.0, output=50.0),
}

# One token per two characters runs high for prose and also covers dense text. The response
# reports the real counts, the estimate only feeds the pre-flight check and the budget guard.
CHARS_PER_TOKEN = 2

ERROR_BODY_LIMIT = 200
SPEND_CAP_CODE = "enforced_spend_limit_reached"
SAFE_NAME = re.compile(r"^[a-z_]{1,40}$")
SAFE_REQUEST_ID = re.compile(r"^req_[A-Za-z0-9]{1,64}$")

# Keywords the structured output grammar rejects with a 400. The pydantic model validates the
# answer afterwards, so dropping them only loses guidance, never a check.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
        "pattern",
        "uniqueItems",
    }
)
SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions"})


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def _close(node: object) -> object:
    """Close every object and drop unsupported keywords. Property names are never touched."""
    if isinstance(node, list):
        return [_close(item) for item in node]
    if not isinstance(node, dict):
        return node
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in SCHEMA_MAPS and isinstance(value, dict):
            result[key] = {name: _close(child) for name, child in value.items()}
        elif (
            key in UNSUPPORTED_KEYWORDS
            or key == "minItems"
            and isinstance(value, int)
            and value > 1
        ):
            continue
        else:
            result[key] = _close(value)
    if result.get("type") == "object" or "properties" in result:
        result["additionalProperties"] = False
    return result


def strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """The pydantic schema rewritten to what the structured output grammar accepts."""
    closed = _close(copy.deepcopy(schema.model_json_schema()))
    assert isinstance(closed, dict)
    return closed


def build_request(
    model: str, system: str, data_block: str, schema: type[BaseModel], max_output_tokens: int
) -> dict[str, Any]:
    """The Messages API body. `system` is trusted text and the only content of `system`.
    `data_block` is the single user message. No tools are offered, so the model can only answer."""
    return {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": system,
        "messages": [{"role": "user", "content": data_block}],
        "output_config": {"format": {"type": "json_schema", "schema": strict_json_schema(schema)}},
    }


def _count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def reported_usage(body: Mapping[str, Any], provider: str = PROVIDER) -> Usage:
    """Input tokens include any cache fields. Without complete counts the budget cannot be kept."""
    raw = body.get("usage")
    if not isinstance(raw, dict):
        raise ProviderUnavailable(provider, "response has no usable usage")
    input_tokens = _count(raw.get("input_tokens"))
    output_tokens = _count(raw.get("output_tokens"))
    if input_tokens is None or output_tokens is None:
        raise ProviderUnavailable(provider, "response has no usable usage")
    for name in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        if name not in raw:
            continue
        extra = _count(raw[name])
        if extra is None:
            raise ProviderUnavailable(provider, "response has no usable usage")
        input_tokens += extra
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens)


def _text(body: Mapping[str, Any], provider: str) -> str:
    content = body.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise ProviderUnavailable(provider, "response text block is not text")
                parts.append(text)
    if not parts:
        raise ProviderUnavailable(provider, "response has no text content")
    return "".join(parts)


def parse_response[T: BaseModel](
    body: Mapping[str, Any], schema: type[T], provider: str = PROVIDER
) -> StructuredResult[T]:
    """Typed errors for refusals, cut off answers and odd stops. The usage is attached by the
    caller, which has already read it."""
    usage = reported_usage(body, provider)
    stop_reason = body.get("stop_reason")
    if stop_reason == "refusal":
        raise Refusal(provider)
    if stop_reason == "max_tokens":
        raise SchemaViolation(schema.__name__, "the answer was cut off at the output limit")
    if stop_reason != "end_turn":
        named = stop_reason if isinstance(stop_reason, str) and SAFE_NAME.match(stop_reason) else ""
        raise ProviderUnavailable(provider, f"unexpected stop_reason {named or 'unrecognized'}")
    text = _text(body, provider)
    try:
        parsed = schema.model_validate_json(text)
    except ValidationError as error:
        raise SchemaViolation(schema.__name__, describe_validation_error(error)) from None
    return StructuredResult(parsed=parsed, raw_text=text, usage=usage)


def _is_loopback_url(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host == "localhost" or host in ("127.0.0.1", "::1")


class AnthropicProvider:
    def __init__(
        self, settings: ProviderSettings, environ: Mapping[str, str] | None = None
    ) -> None:
        environ = os.environ if environ is None else environ
        self._settings = settings
        if settings.base_url is None and not settings.allow_remote:
            raise ConfigError(
                "the anthropic provider sends data to a hosted service; set allow_remote = true"
            )
        self._base_url = (settings.base_url or DEFAULT_BASE_URL).rstrip("/")
        if not self._base_url.startswith("https://") and not _is_loopback_url(self._base_url):
            raise ConfigError("the anthropic provider needs an https base_url for a remote host")
        key = resolve_api_key(settings, environ)
        if key is None:
            raise ConfigError("the anthropic provider needs api_key_env naming the key variable")
        self._key = key
        self._cost = self._resolve_cost(settings)
        self._context = (
            settings.context_tokens
            if "context_tokens" in settings.model_fields_set
            else DEFAULT_CONTEXT_TOKENS
        )

    @staticmethod
    def _resolve_cost(settings: ProviderSettings) -> CostPerMtok:
        known = KNOWN_PRICES.get(settings.model)
        input_price = settings.input_usd_per_mtok
        output_price = settings.output_usd_per_mtok
        if input_price is None and known is not None:
            input_price = known.input
        if output_price is None and known is not None:
            output_price = known.output
        if input_price is None or output_price is None:
            raise ConfigError(
                f"no known price for model {settings.model!r}; "
                "set input_usd_per_mtok and output_usd_per_mtok"
            )
        return CostPerMtok(input=input_price, output=output_price)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            context_tokens=self._context, strict_schema=True, local=False, cost_per_mtok=self._cost
        )

    def count_tokens_estimate(self, text: str) -> int:
        return estimate_tokens(text)

    def complete_structured[T: BaseModel](
        self, system: str, data_block: str, schema: type[T], max_output_tokens: int
    ) -> StructuredResult[T]:
        needed = estimate_input_tokens(self, system, data_block, schema) + max_output_tokens
        if needed > self._context:
            raise ContextTruncated(needed, self._context)
        request = build_request(self._settings.model, system, data_block, schema, max_output_tokens)
        observed: Usage | None = None
        try:
            body = self._post(request)
            try:
                observed = reported_usage(body)
            except ProviderUnavailable:
                observed = None
            return parse_response(body, schema)
        except ProviderError as error:
            error.mark_attempt(observed)
            raise

    def _post(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self._key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        timeout = httpx.Timeout(
            self._settings.request_timeout_seconds, connect=self._settings.connect_timeout_seconds
        )
        try:
            response = httpx.post(
                f"{self._base_url}{MESSAGES_PATH}", json=request, headers=headers, timeout=timeout
            )
        except httpx.HTTPError as error:
            raise ProviderUnavailable(
                PROVIDER, f"{type(error).__name__} at {self._base_url}", secrets=[self._key]
            ) from None
        self._check_status(response)
        try:
            body = response.json()
        except ValueError:
            raise ProviderUnavailable(PROVIDER, "response is not JSON") from None
        if not isinstance(body, dict):
            raise ProviderUnavailable(PROVIDER, "response is not a JSON object")
        return body

    def _check_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        detail = _error_detail(response)
        if status in (429, 529):
            if detail.code == SPEND_CAP_CODE:
                raise ProviderUnavailable(
                    PROVIDER,
                    f"HTTP {status}: the organization spend cap is reached{detail.request_id}",
                )
            raise RateLimited(_retry_after(response))
        raise ProviderUnavailable(
            PROVIDER,
            f"HTTP {status}: {detail.message}{detail.request_id}",
            secrets=[self._key],
        )


class _ErrorDetail:
    def __init__(self, message: str, code: str, request_id: str) -> None:
        self.message = message
        self.code = code
        self.request_id = request_id


def _error_detail(response: httpx.Response) -> _ErrorDetail:
    message = ""
    code = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        text = error.get("message")
        kind = error.get("type")
        message = " ".join(
            part
            for part in (
                kind if isinstance(kind, str) and SAFE_NAME.match(kind) else "",
                text[:ERROR_BODY_LIMIT] if isinstance(text, str) else "",
            )
            if part
        )
        details = error.get("details")
        if isinstance(details, dict) and isinstance(details.get("error_code"), str):
            code = details["error_code"]
    raw_id = response.headers.get("request-id", "")
    request_id = f" ({raw_id})" if SAFE_REQUEST_ID.match(raw_id) else ""
    return _ErrorDetail(message, code, request_id)


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


REGISTRY.register(PROVIDER, AnthropicProvider)
