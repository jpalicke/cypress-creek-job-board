# ABOUTME: The published score formula: a weighted average of support over all requirements.
# ABOUTME: Pure arithmetic, no model and no clock, and support can only ever be downgraded.
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cypress_creek.ingest.models import Importance
from cypress_creek.scoring.support import Support

_ORDER = (Support.NONE, Support.PARTIAL, Support.STRONG)


def _rank(support: Support) -> int:
    return _ORDER.index(support)


def downgrade(support: Support) -> Support:
    """One step lower, stopping at none. There is deliberately no way to raise support."""
    return _ORDER[max(_rank(support) - 1, 0)]


class Weights(BaseModel):
    """Importance weights and support values. The defaults are the published ones."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required: float = Field(default=3, gt=0)
    unspecified: float = Field(default=2, gt=0)
    preferred: float = Field(default=1, gt=0)
    strong: float = Field(default=1.0, ge=0, le=1)
    partial: float = Field(default=0.5, ge=0, le=1)
    none: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _support_values_must_not_decrease_with_support(self) -> "Weights":
        if not self.none <= self.partial <= self.strong:
            raise ValueError("support values must satisfy none <= partial <= strong")
        return self

    def weight_of(self, importance: Importance) -> float:
        return {
            Importance.REQUIRED: self.required,
            Importance.UNSPECIFIED: self.unspecified,
            Importance.PREFERRED: self.preferred,
        }[importance]

    def value_of(self, support: Support) -> float:
        return {
            Support.STRONG: self.strong,
            Support.PARTIAL: self.partial,
            Support.NONE: self.none,
        }[support]


class Match(BaseModel):
    """A requirement's final support, with the ceiling the deterministic gate allowed.

    Entailment may confirm the ceiling or lower it by one step. Anything else is refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    importance: Importance
    ceiling: Support
    support: Support

    @model_validator(mode="after")
    def _support_may_only_be_downgraded_one_step(self) -> "Match":
        drop = _rank(self.ceiling) - _rank(self.support)
        if drop < 0:
            raise ValueError(f"{self.requirement_id}: support is above its ceiling")
        if drop > 1:
            raise ValueError(f"{self.requirement_id}: support dropped more than one step")
        return self


class ScoreLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    importance: Importance
    support: Support
    weight: float
    value: float


class ScoreInputs(BaseModel):
    """Every weight and value used, so the score can be recomputed by hand."""

    model_config = ConfigDict(frozen=True)

    weights: Weights
    lines: list[ScoreLine]


class ScoreResult(BaseModel):
    """score is None when there were no requirements: that is "no score", never 100 or 0."""

    model_config = ConfigDict(frozen=True)

    score: float | None
    supported: int
    total: int
    counts: dict[Support, int]
    inputs: ScoreInputs


def score(matches: Sequence[Match], weights: Weights | None = None) -> ScoreResult:
    """100 * sum(weight * value) / sum(weight) over all requirements. Supported means partial
    or strong, and the counts show the split."""
    weights = weights or Weights()
    lines = [
        ScoreLine(
            requirement_id=m.requirement_id,
            importance=m.importance,
            support=m.support,
            weight=weights.weight_of(m.importance),
            value=weights.value_of(m.support),
        )
        for m in matches
    ]
    total_weight = sum(line.weight for line in lines)
    result = 100 * sum(line.weight * line.value for line in lines) / total_weight if lines else None
    return ScoreResult(
        score=result,
        supported=sum(1 for m in matches if m.support != Support.NONE),
        total=len(matches),
        counts={level: sum(1 for m in matches if m.support == level) for level in _ORDER[::-1]},
        inputs=ScoreInputs(weights=weights, lines=lines),
    )
