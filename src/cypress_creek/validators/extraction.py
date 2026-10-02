# ABOUTME: Validators for model extraction output: V1 schema, V2 verbatim span, V3 importance cues.
# ABOUTME: Pure functions over untrusted model output, no model and no network.
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from cypress_creek.ingest.models import Requirement
from cypress_creek.validators.cues import cue_importance
from cypress_creek.validators.verdict import Verdict, fail, ok


def check_schema(model: type[BaseModel], data: str | bytes | Mapping[str, Any]) -> Verdict:
    """V1: the output parses and conforms to the model, with no extra fields."""
    try:
        if isinstance(data, str | bytes):
            model.model_validate_json(data, strict=True)
        else:
            model.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "output"
        return fail("V1", f"{location}: {first['msg']}", location)
    return ok("V1")


def check_verbatim_span(posting_text: str, requirement: Requirement) -> Verdict:
    """V2: the requirement text equals posting[span.start:span.end]."""
    start, end = requirement.span
    if posting_text[start:end] != requirement.text:
        return fail("V2", "text is not the posting text at its span", requirement.text)
    return ok("V2")


def check_importance(posting_text: str, requirement: Requirement) -> Verdict:
    """V3: importance agrees with the cue words in or near the span."""
    expected = cue_importance(posting_text, requirement.span)
    if requirement.importance != expected:
        return fail(
            "V3",
            f"importance {requirement.importance.value} conflicts with cues, "
            f"expected {expected.value}",
            requirement.importance.value,
        )
    return ok("V3")
