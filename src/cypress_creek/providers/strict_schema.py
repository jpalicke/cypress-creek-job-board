# ABOUTME: Turns a pydantic model's JSON schema into the strict subset hosted APIs accept.
# ABOUTME: Dropped constraints are still enforced locally, because the reply is parsed by pydantic.
import copy
from typing import Any

from pydantic import BaseModel

# Keywords the strict structured output modes of the hosted APIs reject. Pydantic validates the
# reply against the original model, so dropping them here loses no check.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "default",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maxItems",
        "maxLength",
        "maximum",
        "minLength",
        "minimum",
        "multipleOf",
        "uniqueItems",
    }
)
MAX_MIN_ITEMS = 1


def strict_schema(model: type[BaseModel], require_all: bool = False) -> dict[str, Any]:
    """A copy of the model's schema with unsupported keywords removed and objects closed.

    `require_all` lists every property as required, which OpenAI's strict mode demands. Optional
    fields stay nullable through the schema's own `anyOf` with null.
    """
    schema = copy.deepcopy(model.model_json_schema())
    return _strict_node(schema, require_all)


def _strict_node(node: dict[str, Any], require_all: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in UNSUPPORTED_KEYWORDS:
            continue
        if key == "minItems" and value > MAX_MIN_ITEMS:
            continue
        if key in ("properties", "$defs"):
            result[key] = {name: _strict_child(child, require_all) for name, child in value.items()}
        else:
            result[key] = _strict_child(value, require_all)
    if result.get("type") == "object" or "properties" in result:
        result["additionalProperties"] = False
        if require_all:
            result["required"] = list(result.get("properties", {}))
    return result


def _strict_child(value: Any, require_all: bool) -> Any:
    if isinstance(value, dict):
        return _strict_node(value, require_all)
    if isinstance(value, list):
        return [_strict_child(item, require_all) for item in value]
    return value
