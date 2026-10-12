# ABOUTME: The six typed errors a provider raises. Callers branch on the class, never on the text.
# ABOUTME: Free text fields are scrubbed of secrets at construction so no message can leak a key.
from collections.abc import Sequence

REDACTED = "[redacted]"


def scrub(text: str, secrets: Sequence[str]) -> str:
    """Replace every non-empty secret in the text."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class ProviderError(Exception):
    """Base class for every error a provider raises."""


class ContextTruncated(ProviderError):
    """The input exceeded context or matched a reported truncation signature. Never retried."""

    def __init__(
        self, input_tokens: int, context_tokens: int, *, detected_after_call: bool = False
    ) -> None:
        if detected_after_call:
            message = (
                f"server reported {input_tokens} prompt tokens matching a truncation signature "
                f"for context of {context_tokens}"
            )
        else:
            message = f"input of {input_tokens} tokens exceeds context of {context_tokens}"
        super().__init__(message)
        self.input_tokens = input_tokens
        self.context_tokens = context_tokens


class SchemaViolation(ProviderError):
    """The output did not match the schema. Retried once. `detail` is the schema error only,
    never the model output."""

    def __init__(self, schema_name: str, detail: str, secrets: Sequence[str] = ()) -> None:
        self.schema_name = schema_name
        self.detail = scrub(detail, secrets)
        super().__init__(f"output does not match {schema_name}: {self.detail}")


class ProviderUnavailable(ProviderError):
    """The backend could not be reached or failed."""

    def __init__(self, provider: str, reason: str, secrets: Sequence[str] = ()) -> None:
        self.provider = provider
        self.reason = scrub(reason, secrets)
        super().__init__(f"{provider} unavailable: {self.reason}")


class RateLimited(ProviderError):
    """The backend asked us to slow down. Retried with bounded backoff."""

    def __init__(self, retry_after_seconds: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after_seconds = retry_after_seconds


class BudgetExceeded(ProviderError):
    """A run limit would be passed. `limit_name` is input_tokens, output_tokens, requests or usd.
    Never retried."""

    def __init__(self, limit_name: str, limit: float, would_reach: float) -> None:
        super().__init__(
            f"{limit_name} limit {limit:g} would be exceeded, reaching {would_reach:g}"
        )
        self.limit_name = limit_name
        self.limit = limit
        self.would_reach = would_reach


class Refusal(ProviderError):
    """The model declined to answer. Never retried."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider} refused to answer")
        self.provider = provider
