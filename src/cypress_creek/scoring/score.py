# ABOUTME: The published score formula: a weighted average of support over all requirements.
# ABOUTME: Pure arithmetic, no model and no clock, and support can only ever be downgraded.
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cypress_creek.ingest.models import Importance
from cypress_creek.scoring.support import Support

DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parents[3] / "config" / "weights.yaml"

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


class WeightsError(Exception):
    """The weights file is missing, malformed or holds invalid values."""


def load_weights(path: Path = DEFAULT_WEIGHTS_PATH) -> Weights:
    if not path.is_file():
        raise WeightsError(f"weights file not found: {path}")
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf8"))
    except yaml.YAMLError as error:
        raise WeightsError(f"invalid YAML in weights file: {error}") from error
    if not isinstance(data, Mapping) or not isinstance(data.get("weights"), Mapping):
        raise WeightsError("weights file needs a top level 'weights' mapping")
    try:
        return Weights(**data["weights"])
    except (ValidationError, TypeError) as error:
        raise WeightsError(f"invalid weights: {error}") from error


class Match(BaseModel):
    """A requirement's final support, with the ceiling the deterministic gate allowed.

    Entailment may confirm the ceiling or lower it. Support above the ceiling is refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    importance: Importance
    ceiling: Support
    support: Support

    @model_validator(mode="after")
    def _support_may_not_exceed_its_ceiling(self) -> "Match":
        if _rank(self.support) > _rank(self.ceiling):
            raise ValueError(f"{self.requirement_id}: support is above its ceiling")
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
