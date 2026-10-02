# ABOUTME: Run limits and the tracker that enforces them: checked before a call, updated after it.
# ABOUTME: Fails closed. Real usage above an estimate blocks every later call.
from pydantic import BaseModel, ConfigDict, Field

from cypress_creek.providers.base import (
    Capabilities,
    CostPerMtok,
    Provider,
    StructuredResult,
    Usage,
    estimate_input_tokens,
)
from cypress_creek.providers.errors import BudgetExceeded

TOKENS_PER_MTOK = 1_000_000


class Budget(BaseModel):
    """Per run limits. The dollar limit only bites on a backend with a price."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_input_tokens: int = Field(default=500_000, gt=0)
    max_output_tokens: int = Field(default=100_000, gt=0)
    max_requests: int = Field(default=500, gt=0)
    max_usd: float = Field(default=2.0, gt=0)


class BudgetTracker:
    def __init__(self, budget: Budget, cost_per_mtok: CostPerMtok) -> None:
        self.budget = budget
        self._cost_per_mtok = cost_per_mtok
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0
        self.usd = 0.0

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self._cost_per_mtok.input + output_tokens * self._cost_per_mtok.output
        ) / TOKENS_PER_MTOK

    def check_before(self, input_tokens: int, max_output_tokens: int) -> None:
        """Raise BudgetExceeded if a call with this estimate and output cap could pass a limit.

        The output cap is the worst case, so the dollar check is a ceiling on what the call costs.
        """
        limits = self.budget
        projected = {
            "input_tokens": (limits.max_input_tokens, self.input_tokens + input_tokens),
            "output_tokens": (limits.max_output_tokens, self.output_tokens + max_output_tokens),
            "requests": (limits.max_requests, self.requests + 1),
            "usd": (limits.max_usd, self.usd + self.cost_usd(input_tokens, max_output_tokens)),
        }
        for name, (limit, would_reach) in projected.items():
            if would_reach > limit:
                raise BudgetExceeded(name, limit, would_reach)

    def record(self, usage: Usage) -> None:
        """Add what the server reported. It never raises, the next check_before does."""
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.requests += 1
        self.usd += self.cost_usd(usage.input_tokens, usage.output_tokens)


class BudgetedProvider:
    """Wraps any provider so each call is checked against the budget and its usage recorded."""

    def __init__(self, inner: Provider, tracker: BudgetTracker) -> None:
        self._inner = inner
        self.tracker = tracker

    @property
    def capabilities(self) -> Capabilities:
        return self._inner.capabilities

    def count_tokens_estimate(self, text: str) -> int:
        return self._inner.count_tokens_estimate(text)

    def complete_structured[T: BaseModel](
        self, system: str, data_block: str, schema: type[T], max_output_tokens: int
    ) -> StructuredResult[T]:
        estimate = estimate_input_tokens(self._inner, system, data_block, schema)
        self.tracker.check_before(estimate, max_output_tokens)
        result = self._inner.complete_structured(system, data_block, schema, max_output_tokens)
        self.tracker.record(result.usage)
        return result
