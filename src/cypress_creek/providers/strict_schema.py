# ABOUTME: Turns a pydantic model's JSON schema into the strict subset hosted APIs accept.
# ABOUTME: Dropped constraints are still enforced locally, because the reply is parsed by pydantic.
import copy
from typing import Any

from pydantic import BaseModel

MAX_MIN_ITEMS = 1
# Maps whose keys are names, not keywords, so a property called `pattern` is never dropped.
SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions"})


def strict_schema(
    model: type[BaseModel], keywords_to_drop: frozenset[str], require_all: bool = False
) -> dict[str, Any]:
    """A copy of the model's schema with the provider's unsupported keywords removed and objects
    closed. Each adapter names its own keyword set next to its code.

    `require_all` lists every property as required, which OpenAI's strict mode demands. Optional
    fields stay nullable through the schema's own `anyOf` with null.
    """
    schema = copy.deepcopy(model.model_json_schema())
    return close_schema(schema, keywords_to_drop, require_all)


def close_schema(
    node: dict[str, Any], keywords_to_drop: frozenset[str], require_all: bool
) -> dict[str, Any]:
    """Drop the keywords, keep minItems of at most one, and forbid extra properties on objects."""
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in keywords_to_drop:
            continue
        if key == "minItems" and isinstance(value, int) and value > MAX_MIN_ITEMS:
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            result[key] = {
                name: _child(child, keywords_to_drop, require_all) for name, child in value.items()
            }
        else:
            result[key] = _child(value, keywords_to_drop, require_all)
    if result.get("type") == "object" or "properties" in result:
        result["additionalProperties"] = False
        if require_all:
            result["required"] = list(result.get("properties", {}))
    return result


def _child(value: Any, keywords_to_drop: frozenset[str], require_all: bool) -> Any:
    if isinstance(value, dict):
        return close_schema(value, keywords_to_drop, require_all)
    if isinstance(value, list):
        return [_child(item, keywords_to_drop, require_all) for item in value]
    return value
