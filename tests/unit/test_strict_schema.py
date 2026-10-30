# ABOUTME: Tests that pydantic schemas become the strict JSON schema subset hosted APIs accept.
# ABOUTME: Local pydantic validation still enforces every constraint the strict form drops.
from typing import Annotated

from pydantic import BaseModel, Field

from cypress_creek.pipeline.schemas import ExtractionOutput
from cypress_creek.providers.anthropic import ANTHROPIC_UNSUPPORTED_KEYWORDS
from cypress_creek.providers.openai_compatible import OPENAI_UNSUPPORTED_KEYWORDS
from cypress_creek.providers.strict_schema import strict_schema


class Inner(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)]
    count: Annotated[int, Field(ge=0, le=9)] = 3
    note: str | None = None


class Outer(BaseModel):
    items: Annotated[list[Inner], Field(min_length=2, max_length=5)]


def test_every_property_becomes_required_when_asked() -> None:
    schema = strict_schema(Inner, OPENAI_UNSUPPORTED_KEYWORDS, require_all=True)
    assert schema["required"] == ["name", "count", "note"]


def test_optional_properties_stay_optional_by_default() -> None:
    schema = strict_schema(Inner, OPENAI_UNSUPPORTED_KEYWORDS)
    assert schema["required"] == ["name"]


def test_unsupported_constraints_and_defaults_are_dropped_everywhere() -> None:
    schema = strict_schema(Outer, OPENAI_UNSUPPORTED_KEYWORDS, require_all=True)
    banned = {"minLength", "maxLength", "minimum", "maximum", "maxItems", "default"}
    assert _keys(schema).isdisjoint(banned)
    assert "minItems" not in schema["properties"]["items"]


def test_min_items_of_one_is_kept() -> None:
    class One(BaseModel):
        items: Annotated[list[str], Field(min_length=1)]

    assert strict_schema(One, OPENAI_UNSUPPORTED_KEYWORDS)["properties"]["items"]["minItems"] == 1


def test_every_object_forbids_additional_properties() -> None:
    schema = strict_schema(Outer, OPENAI_UNSUPPORTED_KEYWORDS)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Inner"]["additionalProperties"] is False


def test_the_source_model_schema_is_not_modified() -> None:
    before = Outer.model_json_schema()
    strict_schema(Outer, OPENAI_UNSUPPORTED_KEYWORDS, require_all=True)
    assert Outer.model_json_schema() == before


def test_the_real_extraction_schema_is_strict_with_every_field_required() -> None:
    schema = strict_schema(ExtractionOutput, OPENAI_UNSUPPORTED_KEYWORDS, require_all=True)
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


class Patterned(BaseModel):
    code: Annotated[str, Field(pattern="^[A-Z]+$")] = "AB"


def test_each_provider_has_its_own_keyword_set_and_the_set_decides_what_is_dropped() -> None:
    openai = strict_schema(Patterned, OPENAI_UNSUPPORTED_KEYWORDS)
    anthropic = strict_schema(Patterned, ANTHROPIC_UNSUPPORTED_KEYWORDS)

    assert openai["properties"]["code"]["pattern"] == "^[A-Z]+$"
    assert "default" not in openai["properties"]["code"]
    assert "pattern" not in anthropic["properties"]["code"]
    assert anthropic["properties"]["code"]["default"] == "AB"


def test_the_two_sets_differ_in_exactly_the_documented_keywords() -> None:
    assert {"default"} == OPENAI_UNSUPPORTED_KEYWORDS - ANTHROPIC_UNSUPPORTED_KEYWORDS
    assert {"pattern"} == ANTHROPIC_UNSUPPORTED_KEYWORDS - OPENAI_UNSUPPORTED_KEYWORDS


def test_an_empty_keyword_set_drops_only_large_min_items() -> None:
    schema = strict_schema(Outer, frozenset())
    assert schema["properties"]["items"]["maxItems"] == 5
    assert "minItems" not in schema["properties"]["items"]


def test_a_property_named_like_a_dropped_keyword_survives() -> None:
    class Named(BaseModel):
        pattern: str
        default: str

    schema = strict_schema(Named, ANTHROPIC_UNSUPPORTED_KEYWORDS | OPENAI_UNSUPPORTED_KEYWORDS)

    assert set(schema["properties"]) == {"pattern", "default"}


def test_definitions_maps_are_walked_like_defs() -> None:
    node = {"definitions": {"X": {"type": "object", "maxItems": 3, "properties": {}}}}
    from cypress_creek.providers.strict_schema import close_schema

    result = close_schema(node, OPENAI_UNSUPPORTED_KEYWORDS, require_all=False)

    assert result["definitions"]["X"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
