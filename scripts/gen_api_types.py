# ABOUTME: Generates web/src/lib/types.ts from the API's pydantic models, so UI types cannot drift.
# ABOUTME: Run `uv run python scripts/gen_api_types.py`; a unit test fails when the file is stale.
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cypress_creek.api.routes.facts import RemovedResponse, ShareRequest
from cypress_creek.api.routes.health import HealthResponse
from cypress_creek.api.routes.imports import (
    ApprovedResponse,
    CandidatesResponse,
    ImportResponse,
    ResumeRequest,
)
from cypress_creek.api.routes.providers import ProvidersResponse
from cypress_creek.api.routes.session import SessionResponse
from cypress_creek.api.routes.suggestions import SuggestionRequest, SuggestionResponse
from cypress_creek.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    EstimateResponse,
    FactsResponse,
    PostingRequest,
    PostingResponse,
    ReportResponse,
)
from cypress_creek.facts.store import FactDraft

OUTPUT = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "types.ts"
API_MODELS: list[type[BaseModel]] = [
    HealthResponse,
    ProvidersResponse,
    SessionResponse,
    PostingRequest,
    PostingResponse,
    EstimateResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    ReportResponse,
    SuggestionRequest,
    SuggestionResponse,
    FactsResponse,
    FactDraft,
    ShareRequest,
    RemovedResponse,
    ResumeRequest,
    ImportResponse,
    CandidatesResponse,
    ApprovedResponse,
]
HEADER = (
    "// ABOUTME: Types of the API answers, generated from the pydantic models. Do not edit.\n"
    "// ABOUTME: Regenerate with `uv run python scripts/gen_api_types.py`; a unit test checks it.\n"
)
SCALARS = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean"}


def schema_to_ts(schema: dict[str, Any]) -> str:
    """The TypeScript type of one JSON schema node. Refuses shapes it does not know."""
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if "const" in schema:
        return _literal(schema["const"])
    if "enum" in schema:
        return " | ".join(_literal(value) for value in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(schema_to_ts(option) for option in schema["anyOf"])
    kind = schema.get("type")
    if kind in SCALARS:
        return SCALARS[kind]
    if kind == "null":
        return "null"
    if kind == "array":
        if "prefixItems" in schema:
            return "[" + ", ".join(schema_to_ts(item) for item in schema["prefixItems"]) + "]"
        inner = schema_to_ts(schema["items"])
        return f"({inner})[]" if " | " in inner else f"{inner}[]"
    if kind == "object" and "properties" not in schema:
        extra = schema.get("additionalProperties")
        value = schema_to_ts(extra) if isinstance(extra, dict) else "unknown"
        return f"Record<string, {value}>"
    raise ValueError(f"unsupported schema node: {schema}")


def _literal(value: object) -> str:
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value).lower() if isinstance(value, bool) else str(value)


def _declaration(name: str, schema: dict[str, Any]) -> str:
    if schema.get("type") == "object" and "properties" in schema:
        lines = [f"export interface {name} {{"]
        for field, node in schema["properties"].items():
            lines.append(f"  {field}: {schema_to_ts(node)};")
        lines.append("}")
        return "\n".join(lines)
    return f"export type {name} = {schema_to_ts(schema)};"


def render(models: list[type[BaseModel]]) -> str:
    """All models and everything they refer to, in a stable order. Answers are described in
    serialization mode, so a field with a default is always present."""
    declarations: dict[str, dict[str, Any]] = {}
    for model in models:
        schema = model.model_json_schema(mode="serialization")
        for name, definition in schema.pop("$defs", {}).items():
            declarations[name] = definition
        declarations[schema.get("title", model.__name__)] = schema
    body = "\n\n".join(_declaration(name, declarations[name]) for name in sorted(declarations))
    return HEADER + "\n" + body + "\n"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(API_MODELS), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
