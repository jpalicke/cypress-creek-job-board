# ABOUTME: Records observed provider attempts and validator verdicts from pipeline execution.
# ABOUTME: Missing usage stays unknown; validator verdicts may retain offending text.
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cypress_creek.providers.base import CostPerMtok, Usage
from cypress_creek.providers.budget import TOKENS_PER_MTOK
from cypress_creek.validators.verdict import Verdict

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[str, StringConstraints(min_length=1)]


class CallRecord(BaseModel):
    """One observed provider attempt, including retry attempts as separate entries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Name
    prompt_hash: Digest
    schema_version: int = Field(gt=0)
    outcome: Literal["success", "error"] = "success"
    error_type: Name | None = None
    usage: Usage | None
    cost_usd: float | None = Field(ge=0)

    @model_validator(mode="after")
    def validate_outcome(self) -> "CallRecord":
        if (self.outcome == "error") != (self.error_type is not None):
            raise ValueError("error outcome needs an error type, success cannot have one")
        if (self.usage is None) != (self.cost_usd is None):
            raise ValueError("usage and cost must both be known or both be unknown")
        if self.outcome == "success" and self.usage is None:
            raise ValueError("successful call needs reported usage")
        return self


class ValidatorRecord(BaseModel):
    """A verdict with the stage and subject checked by a production validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Name
    subject: Name
    verdict: Verdict


class PipelineTrace:
    """Mutable ordered records for one pipeline analysis."""

    def __init__(self) -> None:
        self.calls: list[CallRecord] = []
        self.validators: list[ValidatorRecord] = []

    def record_call(
        self,
        *,
        stage: str,
        prompt_hash: str,
        schema_version: int,
        usage: Usage | None,
        cost_per_mtok: CostPerMtok,
        error_type: str | None = None,
    ) -> None:
        """Append one observed attempt without inferring missing usage or cost."""
        cost_usd = (
            None
            if usage is None
            else (
                usage.input_tokens * cost_per_mtok.input
                + usage.output_tokens * cost_per_mtok.output
            )
            / TOKENS_PER_MTOK
        )
        self.calls.append(
            CallRecord(
                stage=stage,
                prompt_hash=prompt_hash,
                schema_version=schema_version,
                outcome="error" if error_type else "success",
                error_type=error_type,
                usage=usage,
                cost_usd=cost_usd,
            )
        )

    def record_validator(self, stage: str, subject: str, verdict: Verdict) -> None:
        """Append the verdict returned by a validator that actually ran."""
        self.validators.append(ValidatorRecord(stage=stage, subject=subject, verdict=verdict))
