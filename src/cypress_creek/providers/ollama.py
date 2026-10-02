# ABOUTME: The Ollama adapter, built on the native /api/chat endpoint so num_ctx is set per request.
# ABOUTME: A pre-flight and a post-flight check refuse prompts the server would silently truncate.
import json
import math

from pydantic import BaseModel

from cypress_creek.config import ProviderSettings
from cypress_creek.providers.base import Capabilities, CostPerMtok, StructuredResult
from cypress_creek.providers.errors import ContextTruncated
from cypress_creek.providers.factory import REGISTRY

DEFAULT_BASE_URL = "http://localhost:11434"

# Conservative: real tokenizers average nearer four characters per token, so the estimate runs
# high and the guard errs toward refusing.
CHARS_PER_TOKEN = 3

# Ollama drops the start of an over-long prompt, which is where the trusted instructions live,
# and reports a prompt count at the window. A count this close to num_ctx that the estimate did
# not predict is treated as truncation.
NEAR_FULL_FRACTION = 0.95


def estimate_tokens(text: str, chars_per_token: int = CHARS_PER_TOKEN) -> int:
    return math.ceil(len(text) / chars_per_token)


def check_pre_flight(input_tokens: int, max_output_tokens: int, num_ctx: int) -> None:
    """Refuse before calling when the input plus the output cap cannot fit the window."""
    needed = input_tokens + max_output_tokens
    if needed > num_ctx:
        raise ContextTruncated(needed, num_ctx)


def check_post_flight(reported_tokens: int, estimated_tokens: int, num_ctx: int) -> None:
    """Treat a reported prompt count at or near the window as truncation the estimate missed."""
    near_full = num_ctx * NEAR_FULL_FRACTION
    if reported_tokens >= near_full and estimated_tokens < near_full:
        raise ContextTruncated(reported_tokens, num_ctx)


class OllamaProvider:
    def __init__(self, settings: ProviderSettings, chars_per_token: int = CHARS_PER_TOKEN) -> None:
        self._settings = settings
        self._base_url = (settings.base_url or DEFAULT_BASE_URL).rstrip("/")
        self._num_ctx = settings.context_tokens
        self._chars_per_token = chars_per_token

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
        schema_text = json.dumps(schema.model_json_schema())
        input_tokens = sum(self.count_tokens_estimate(t) for t in (system, data_block, schema_text))
        check_pre_flight(input_tokens, max_output_tokens, self._num_ctx)
        raise NotImplementedError


REGISTRY.register("ollama", OllamaProvider)
