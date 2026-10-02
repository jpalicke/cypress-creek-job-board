# ABOUTME: The interface every model backend implements, and the plain data it exchanges.
# ABOUTME: System text and the untrusted data block are separate arguments, so they never merge.
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class CostPerMtok(BaseModel):
    """Dollars per million tokens. Local backends use zero."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: float = Field(ge=0)
    output: float = Field(ge=0)


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_tokens: int = Field(gt=0)
    strict_schema: bool
    local: bool
    cost_per_mtok: CostPerMtok


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class StructuredResult[T: BaseModel](BaseModel):
    """The parsed model, the raw text it came from and what the call used."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parsed: T
    raw_text: str
    usage: Usage


class Provider(Protocol):
    """A model backend. `system` is trusted and static. `data_block` is untrusted posting text."""

    @property
    def capabilities(self) -> Capabilities: ...

    def complete_structured[T: BaseModel](
        self, system: str, data_block: str, schema: type[T], max_output_tokens: int
    ) -> StructuredResult[T]: ...

    def count_tokens_estimate(self, text: str) -> int: ...


def estimate_input_tokens[T: BaseModel](
    provider: Provider, system: str, data_block: str, schema: type[T]
) -> int:
    """The provider's own estimate for everything a call sends: system, data and schema text."""
    schema_text = json.dumps(schema.model_json_schema())
    return sum(provider.count_tokens_estimate(t) for t in (system, data_block, schema_text))
