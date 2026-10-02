# ABOUTME: The common result type every validator returns: passed, validator id, reason, offender.
# ABOUTME: Verdicts are plain data so the eval harness can record them next to production runs.
from pydantic import BaseModel, ConfigDict


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validator: str
    passed: bool
    reason: str = ""
    offending: str | None = None


def ok(validator: str) -> Verdict:
    return Verdict(validator=validator, passed=True)


def fail(validator: str, reason: str, offending: str | None = None) -> Verdict:
    return Verdict(validator=validator, passed=False, reason=reason, offending=offending)
