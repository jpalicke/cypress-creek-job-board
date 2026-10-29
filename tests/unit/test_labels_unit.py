# ABOUTME: Unit tests for the pure parts of the label module: planted gap keys and table reading.
# ABOUTME: These use tiny inline tables, so the real PLANTED_GAPS.md is covered by component tests.
from pathlib import Path

from cypress_creek.scoring.support import Support
from evals.harness.labels import planted_gap_key, planted_gap_support


def test_the_key_joins_kind_term_years_and_issuer() -> None:
    assert planted_gap_key("skill", "Python", None, None) == "skill:python"
    assert planted_gap_key("skill", " PYTHON ", 3, None) == "skill:python:3"
    assert planted_gap_key("certification", "statistics", None, "Some Issuer") == (
        "certification:statistics@some issuer"
    )


def test_the_table_reader_skips_prose_header_and_separator_rows(tmp_path: Path) -> None:
    table = tmp_path / "gaps.md"
    table.write_text(
        "# Title\n\nSome prose | with a pipe\n\n"
        "| Kind | Term | Years | Issuer | Support | Gate | Why |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| skill | rust | | | none | no_candidate | None. |\n"
        "| skill | python | 10 | | partial | years_below | Short. |\n",
        encoding="utf-8",
    )

    assert planted_gap_support(table) == {
        "skill:rust": Support.NONE,
        "skill:python:10": Support.PARTIAL,
    }
