# ABOUTME: Runs the table CLI over real run files and metrics files in a temporary results folder.
# ABOUTME: The committed table must regenerate byte for byte, and a stale or edited one must fail.
from pathlib import Path

import pytest
from table_support import CASES, call, header, publish

from evals.harness.table import (
    README_END,
    README_START,
    Target,
    collect_rows,
    load_targets,
    main,
    render_table,
)

ROOT = Path(__file__).resolve().parents[2]
BACKENDS_YAML = """
targets:
  - label: Local four
    backend: ollama
    model: qwen3.5:4b
  - label: Local nine
    backend: ollama
    model: qwen3.5:9b
  - label: Studio
    backend: openai_compatible
    model: null
  - label: Hosted
    backend: openai_compatible
    model: gpt-6-luna
"""


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    results = tmp_path / "results"
    results.mkdir()
    backends = tmp_path / "backends.yaml"
    backends.write_text(BACKENDS_YAML, encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(f"# Title\n\n{README_START}\nold\n{README_END}\n\nAfter.\n", encoding="utf-8")
    return {"results": results, "backends": backends, "readme": readme, "page": tmp_path / "r.md"}


def argv(ws: dict[str, Path], *extra: str) -> list[str]:
    return [
        "--results",
        str(ws["results"]),
        "--backends",
        str(ws["backends"]),
        "--page",
        str(ws["page"]),
        "--readme",
        str(ws["readme"]),
        *extra,
    ]


def targets(ws: dict[str, Path]) -> list[Target]:
    return load_targets(ws["backends"])


def test_the_table_regenerates_byte_for_byte_and_check_passes(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    publish(workspace["results"], header())
    assert main(argv(workspace)) == 0
    page = workspace["page"].read_bytes()
    readme = workspace["readme"].read_bytes()

    assert main(argv(workspace)) == 0
    assert workspace["page"].read_bytes() == page
    assert workspace["readme"].read_bytes() == readme
    assert main(argv(workspace, "--check")) == 0
    assert "current" in capsys.readouterr().out
    text = readme.decode()
    assert text.startswith("# Title") and text.endswith("After.\n")
    assert "Local four" in text and "old" not in text


def test_an_edited_page_or_readme_block_is_detected(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    publish(workspace["results"], header())
    main(argv(workspace))
    capsys.readouterr()

    workspace["page"].write_text(workspace["page"].read_text() + "hand edit\n", encoding="utf-8")
    assert main(argv(workspace, "--check")) == 1
    assert "r.md is out of date" in capsys.readouterr().err

    main(argv(workspace))
    workspace["readme"].write_text(
        workspace["readme"].read_text().replace("0.750", "0.999"), encoding="utf-8"
    )
    assert main(argv(workspace, "--check")) == 1
    assert "README.md is out of date" in capsys.readouterr().err


def test_a_new_run_file_makes_the_committed_table_stale(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    main(argv(workspace))
    capsys.readouterr()

    publish(workspace["results"], header())

    assert main(argv(workspace, "--check")) == 1
    assert "out of date" in capsys.readouterr().err


def test_numbers_come_from_the_metrics_and_the_recorded_calls(workspace: dict[str, Path]) -> None:
    head = header()
    calls = {
        (case_id, repeat): [
            call(0.01),
            call(0.01, "SchemaViolation" if repeat == 2 and case_id == "case-a" else None),
        ]
        for case_id in CASES
        for repeat in (1, 2, 3)
    }
    publish(workspace["results"], head, calls=calls)

    (row,) = [r for r in collect_rows(workspace["results"], targets(workspace)) if r.was_run]

    assert row.label == "Local four"
    assert row.recall.mean == pytest.approx(0.75)
    assert row.cost.mean == pytest.approx(0.04)
    assert row.cost.worst == pytest.approx(0.04)
    assert row.schema_failures.mean == pytest.approx((0 + 0.25 + 0) / 3)
    assert row.schema_failures.worst == pytest.approx(0.25)
    assert row.commit == "1" * 12
    assert row.repeats == "3 of 3"


def test_a_repeat_with_an_unknown_cost_is_left_out_not_counted_as_zero(
    workspace: dict[str, Path],
) -> None:
    calls = {
        (case_id, repeat): [call(None, "ProviderUnavailable") if repeat == 1 else call(0.02)]
        for case_id in CASES
        for repeat in (1, 2, 3)
    }
    publish(workspace["results"], header(), calls=calls)

    (row,) = [r for r in collect_rows(workspace["results"], targets(workspace)) if r.was_run]

    assert row.cost.mean == pytest.approx(0.04)
    assert row.cost.worst == pytest.approx(0.04)


def test_every_listed_backend_without_a_run_is_a_not_run_row(workspace: dict[str, Path]) -> None:
    publish(workspace["results"], header())

    rows = collect_rows(workspace["results"], targets(workspace))

    assert [(r.label, r.was_run) for r in rows] == [
        ("Local four", True),
        ("Local nine", False),
        ("Studio", False),
        ("Hosted", False),
    ]
    assert "not run" in render_table(rows)


def test_the_exact_model_beats_the_any_model_entry(workspace: dict[str, Path]) -> None:
    publish(workspace["results"], header("openai_compatible", "gpt-6-luna"), name="hosted")
    publish(workspace["results"], header("openai_compatible", "my-local-model"), name="studio")

    rows = {r.label: r for r in collect_rows(workspace["results"], targets(workspace))}

    assert rows["Hosted"].model == "gpt-6-luna"
    assert rows["Studio"].model == "my-local-model"


def test_a_backend_that_is_not_in_the_list_is_still_shown(workspace: dict[str, Path]) -> None:
    publish(workspace["results"], header("anthropic", "claude-x"))

    rows = collect_rows(workspace["results"], targets(workspace))

    assert "anthropic (not in the backend list)" in [r.label for r in rows]


def test_different_prompt_hashes_are_flagged_in_the_page(workspace: dict[str, Path]) -> None:
    publish(workspace["results"], header(), name="a")
    publish(workspace["results"], header(model="qwen3.5:9b", prompt="e"), name="b")
    main(argv(workspace))

    page = workspace["page"].read_text(encoding="utf-8")

    assert "B (not comparable with A)" in page


def test_only_complete_repeats_count_toward_repeats_scored(workspace: dict[str, Path]) -> None:
    publish(workspace["results"], header(), scored=2)

    (row,) = [r for r in collect_rows(workspace["results"], targets(workspace)) if r.was_run]

    assert row.repeats == "2 of 3"


def test_metrics_without_their_run_file_are_an_error(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    publish(workspace["results"], header())
    next(workspace["results"].glob("*.jsonl")).unlink()

    assert main(argv(workspace)) == 1
    assert "has no run file" in capsys.readouterr().err


def test_a_run_file_without_metrics_is_an_error(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    publish(workspace["results"], header())
    next(workspace["results"].glob("*.json")).unlink()

    assert main(argv(workspace)) == 1
    assert "has no metrics file" in capsys.readouterr().err


def test_a_json_file_that_is_not_a_metrics_file_is_an_error(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    (workspace["results"] / "stray.json").write_text("{}", encoding="utf-8")

    assert main(argv(workspace)) == 1
    assert "stray.json is not a metrics file" in capsys.readouterr().err


def test_a_readme_without_the_markers_is_an_error(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    workspace["readme"].write_text("# No markers\n", encoding="utf-8")

    assert main(argv(workspace)) == 1
    assert README_START in capsys.readouterr().err


def test_a_bad_backend_list_is_an_error(
    workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    workspace["backends"].write_text("targets: [{label: x}]\n", encoding="utf-8")

    assert main(argv(workspace)) == 1
    assert "backend list" in capsys.readouterr().err


def test_the_committed_files_match_the_committed_results() -> None:
    assert main(["--check"]) == 0


def test_the_committed_backend_list_names_the_approved_backends() -> None:
    labels = [t.label for t in load_targets(ROOT / "evals" / "backends.yaml")]

    assert labels[:2] == ["Ollama qwen3.5:4b", "Ollama qwen3.5:9b"]
    assert any("LM Studio" in label for label in labels)
    assert any("OpenAI" in label for label in labels)
    assert any("Anthropic" in label for label in labels)


def test_only_schema_violations_count_as_schema_failures(workspace: dict[str, Path]) -> None:
    calls = {
        (case_id, repeat): [call(0.01), call(0.01, "ProviderUnavailable")]
        for case_id in CASES
        for repeat in (1, 2, 3)
    }
    publish(workspace["results"], header(), calls=calls)

    (row,) = [r for r in collect_rows(workspace["results"], targets(workspace)) if r.was_run]

    assert row.schema_failures.mean == pytest.approx(0.0)
    assert row.schema_failures.worst == pytest.approx(0.0)
