# ABOUTME: Tests that pydantic schemas become the strict JSON schema subset hosted APIs accept.
# ABOUTME: Local pydantic validation still enforces every constraint the strict form drops.
from typing import Annotated

from pydantic import BaseModel, Field

from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.providers.strict_schema import strict_schema


class Inner(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)]
    count: Annotated[int, Field(ge=0, le=9)] = 3
    note: str | None = None


class Outer(BaseModel):
    items: Annotated[list[Inner], Field(min_length=2, max_length=5)]


def test_every_property_becomes_required_when_asked() -> None:
    schema = strict_schema(Inner, require_all=True)
    assert schema["required"] == ["name", "count", "note"]


def test_optional_properties_stay_optional_by_default() -> None:
    schema = strict_schema(Inner)
    assert schema["required"] == ["name"]


def test_unsupported_constraints_and_defaults_are_dropped_everywhere() -> None:
    schema = strict_schema(Outer, require_all=True)
    banned = {"minLength", "maxLength", "minimum", "maximum", "maxItems", "default"}
    assert _keys(schema).isdisjoint(banned)
    assert "minItems" not in schema["properties"]["items"]


def test_min_items_of_one_is_kept() -> None:
    class One(BaseModel):
        items: Annotated[list[str], Field(min_length=1)]

    assert strict_schema(One)["properties"]["items"]["minItems"] == 1


def test_every_object_forbids_additional_properties() -> None:
    schema = strict_schema(Outer)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Inner"]["additionalProperties"] is False


def test_the_source_model_schema_is_not_modified() -> None:
    before = Outer.model_json_schema()
    strict_schema(Outer, require_all=True)
    assert Outer.model_json_schema() == before


def test_the_real_extraction_schema_is_strict_with_every_field_required() -> None:
    schema = strict_schema(ExtractionOutput, require_all=True)
    requirement = schema["$defs"]["ProposedRequirement"]
    assert requirement["required"] == [
        "text",
        "kind",
        "term",
        "years",
        "issuer",
        "importance",
    ]


def _keys(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(node, list):
        for value in node:
            found |= _keys(value)
    return found
