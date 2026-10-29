# ABOUTME: Tests the generator that turns the API's pydantic models into TypeScript types.
# ABOUTME: The committed web/src/lib/types.ts must equal the generated text, so it cannot drift.
from pathlib import Path
from typing import Literal

from gen_api_types import render, schema_to_ts
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


class Inner(BaseModel):
    name: str


class Outer(BaseModel):
    count: int
    ratio: float
    flag: bool
    kind: Literal["a", "b"]
    maybe: str | None
    inner: Inner
    many: list[Inner]
    pair: tuple[int, int]
    extras: dict[str, int]
    default_text: str = "x"


def test_scalars_enums_nullables_arrays_and_tuples() -> None:
    text = render([Outer])
    assert "export interface Outer {" in text
    assert "  count: number;" in text
    assert "  ratio: number;" in text
    assert "  flag: boolean;" in text
    assert '  kind: "a" | "b";' in text
    assert "  maybe: string | null;" in text
    assert "  inner: Inner;" in text
    assert "  many: Inner[];" in text
    assert "  pair: [number, number];" in text
    assert "  extras: Record<string, number>;" in text


def test_a_field_with_a_default_is_always_present_in_an_answer() -> None:
    assert "  default_text: string;" in render([Outer])


def test_the_output_is_stable_and_has_the_header() -> None:
    assert render([Outer]) == render([Outer])
    assert render([Outer]).startswith("// ABOUTME: ")


def test_a_ref_to_an_enum_becomes_a_named_union() -> None:
    from cypress_creek.pipeline.report import ReportStatus

    class Holder(BaseModel):
        status: ReportStatus

    text = render([Holder])
    assert 'export type ReportStatus = "complete" | "incomplete";' in text
    assert "  status: ReportStatus;" in text


def test_schema_to_ts_refuses_what_it_cannot_express() -> None:
    import pytest

    with pytest.raises(ValueError, match="unsupported"):
        schema_to_ts({"allOf": [{"type": "string"}, {"type": "integer"}]})


def test_the_committed_ui_types_equal_the_generated_ones() -> None:
    from gen_api_types import API_MODELS

    committed = (ROOT / "web" / "src" / "lib" / "types.ts").read_text(encoding="utf-8")
    assert committed == render(API_MODELS), "run: uv run python scripts/gen_api_types.py"
