# ABOUTME: The Ollama adapter, built on the native /api/chat endpoint so num_ctx is set per request.
# ABOUTME: A pre-flight and a post-flight check refuse prompts the server would silently truncate.
import math
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from cypress_creek.config import ConfigError, ProviderSettings, describe_validation_error
from cypress_creek.providers.base import (
    Capabilities,
    CostPerMtok,
    StructuredResult,
    Usage,
    estimate_input_tokens,
)
from cypress_creek.providers.errors import (
    ContextTruncated,
    ProviderUnavailable,
    RateLimited,
    SchemaViolation,
)
from cypress_creek.providers.factory import REGISTRY

DEFAULT_BASE_URL = "http://localhost:11434"

# The estimate runs high for typical prose but can undercount dense tokenization such as CJK.
# The post-flight guard checks the server's reported count for truncation signatures.
CHARS_PER_TOKEN = 3

# Ollama drops the start of an over-long prompt, which is where the trusted instructions live.
# A reported count near the window that the estimate did not predict is treated as truncation.
NEAR_FULL_FRACTION = 0.95

# Measured against Ollama 0.34: a prompt that overflows the window is cut to its first few
# tokens plus about half of the window, and the reported count is that cut length, not num_ctx.
# Windows below 2048 are raised to 2048 by the server, which would move the band, so they are
# refused.
MIN_NUM_CTX = 2048
HALF_WINDOW_SLACK = 16

ERROR_BODY_LIMIT = 200


def estimate_tokens(text: str, chars_per_token: int = CHARS_PER_TOKEN) -> int:
    return math.ceil(len(text) / chars_per_token)


def check_pre_flight(input_tokens: int, max_output_tokens: int, num_ctx: int) -> None:
    """Refuse before calling when the input plus the output cap cannot fit the window."""
    needed = input_tokens + max_output_tokens
    if needed > num_ctx:
        raise ContextTruncated(needed, num_ctx)


def check_post_flight(reported_tokens: int, estimated_tokens: int, num_ctx: int) -> None:
    """Refuse prompt counts matching a truncation signature, even if the estimate was higher."""
    half = num_ctx / 2
    if half <= reported_tokens <= half + HALF_WINDOW_SLACK:
        raise ContextTruncated(reported_tokens, num_ctx, detected_after_call=True)

    near_full = num_ctx * NEAR_FULL_FRACTION
    if estimated_tokens >= near_full:
        return
    if reported_tokens >= near_full:
        raise ContextTruncated(reported_tokens, num_ctx, detected_after_call=True)


class OllamaProvider:
    def __init__(self, settings: ProviderSettings, chars_per_token: int = CHARS_PER_TOKEN) -> None:
        self._settings = settings
        self._base_url = (settings.base_url or DEFAULT_BASE_URL).rstrip("/")
        self._num_ctx = settings.context_tokens
        self._chars_per_token = chars_per_token
        if self._num_ctx < MIN_NUM_CTX:
            raise ConfigError(
                f"context_tokens must be at least {MIN_NUM_CTX} for the ollama provider"
            )

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            context_tokens=self._num_ctx,
            strict_schema=True,
            local=True,
            cost_per_mtok=CostPerMtok(input=0, output=0),
        )

    def count_tokens_estimate(self, text: str) -> int:
        return estimate_tokens(text, self._chars_per_token)

    def complete_structured[T: BaseModel](
        self, system: str, data_block: str, schema: type[T], max_output_tokens: int
    ) -> StructuredResult[T]:
        input_tokens = estimate_input_tokens(self, system, data_block, schema)
        check_pre_flight(input_tokens, max_output_tokens, self._num_ctx)
        body = self._chat(system, data_block, schema, max_output_tokens)
        reported = usage_count(body, "prompt_eval_count")
        check_post_flight(reported, input_tokens, self._num_ctx)
        content = body.get("message", {}).get("content")
        if not isinstance(content, str):
            raise ProviderUnavailable("ollama", "response has no message content")
        try:
            parsed = schema.model_validate_json(content)
        except ValidationError as error:
            raise SchemaViolation(schema.__name__, describe_validation_error(error)) from None
        usage = Usage(input_tokens=reported, output_tokens=usage_count(body, "eval_count"))
        return StructuredResult(parsed=parsed, raw_text=content, usage=usage)

    def _chat[T: BaseModel](
        self, system: str, data_block: str, schema: type[T], max_output_tokens: int
    ) -> dict[str, Any]:
        request = {
            "model": self._settings.model,
            "stream": False,
            # Reasoning output would spend the output cap before the constrained JSON starts.
            "think": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": data_block},
            ],
            "format": schema.model_json_schema(),
            "options": {
                "num_ctx": self._num_ctx,
                "temperature": 0,
                "num_predict": max_output_tokens,
            },
        }
        timeout = httpx.Timeout(
            self._settings.request_timeout_seconds, connect=self._settings.connect_timeout_seconds
        )
        try:
            response = httpx.post(f"{self._base_url}/api/chat", json=request, timeout=timeout)
        except httpx.HTTPError as error:
            raise ProviderUnavailable(
                "ollama", f"{type(error).__name__} at {self._base_url}"
            ) from None
        check_response_status(response)
        return response_object(response)


def usage_count(body: dict[str, Any], field: str) -> int:
    """A usage count from the response. Without one the truncation check cannot run."""
    value = body.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderUnavailable("ollama", f"response has no usable {field}")
    return value


def check_response_status(response: httpx.Response) -> None:
    """Map a failed HTTP status to its typed error. Redirects are not followed, so they fail."""
    if response.status_code == 429:
        raise RateLimited(_retry_after(response))
    if response.status_code != 200:
        raise ProviderUnavailable(
            "ollama", f"HTTP {response.status_code}: {response.text[:ERROR_BODY_LIMIT]}"
        )


def response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ProviderUnavailable("ollama", "response is not JSON") from None
    if not isinstance(body, dict):
        raise ProviderUnavailable("ollama", "response is not a JSON object")
    return body


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


REGISTRY.register("ollama", OllamaProvider)
