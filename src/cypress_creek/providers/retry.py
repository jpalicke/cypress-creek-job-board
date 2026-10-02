# ABOUTME: The one retry policy for provider calls: schema errors once, rate limits with backoff.
# ABOUTME: Every other typed error propagates. The sleeper is injectable so tests never wait.
import time
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from cypress_creek.providers.errors import RateLimited, SchemaViolation


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_rate_limit_retries: int = Field(default=3, ge=0)
    base_delay_seconds: float = Field(default=1.0, gt=0)
    max_delay_seconds: float = Field(default=30.0, gt=0)

    def delay(self, attempt: int, retry_after_seconds: float | None) -> float:
        """Seconds to wait before rate limit retry number `attempt` (counting from 0)."""
        wanted = (
            retry_after_seconds
            if retry_after_seconds is not None
            else self.base_delay_seconds * 2**attempt
        )
        return min(wanted, self.max_delay_seconds)


def call_with_retry[R](
    call: Callable[[str | None], R],
    *,
    sleep: Callable[[float], None] = time.sleep,
    policy: RetryPolicy | None = None,
) -> R:
    """Run `call`. It receives None the first time and, after a SchemaViolation, the schema
    error text alone (never model output). A second SchemaViolation is raised."""
    policy = policy or RetryPolicy()
    feedback: str | None = None
    schema_retried = False
    rate_limit_retries = 0
    while True:
        try:
            return call(feedback)
        except SchemaViolation as error:
            if schema_retried:
                raise
            schema_retried = True
            feedback = error.detail
        except RateLimited as error:
            if rate_limit_retries >= policy.max_rate_limit_retries:
                raise
            sleep(policy.delay(rate_limit_retries, error.retry_after_seconds))
            rate_limit_retries += 1
