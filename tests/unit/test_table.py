# ABOUTME: Unit tests for rendering the backend comparison table from plain row values.
# ABOUTME: A backend with no run says "not run" in every cell, and mixed conditions are flagged.
from evals.harness.table import Cell, Row, render_table, short_hash


def scored(mean: float, worst: float) -> Cell:
    return Cell(mean, worst)


def run_row(
    label: str, *, prompt: str = "p" * 12, fixture: str = "f" * 12, **cells: Cell | int | None
) -> Row:
    values: dict[str, Cell | int | None] = {
        "recall": scored(0.8333333, 0.5),
        "violations": scored(0.0, 0.0),
        "score_shift": Cell(None, None),
        "schema_failures": scored(0.05, 0.1),
        "cost": scored(0.0123456, 0.02),
        **cells,
    }
    return Row(
        label=label,
        model="m",
        status="complete",
        repeats="3 of 3",
        commit="a" * 12,
        prompt_hash=prompt,
        fixture_hash=fixture,
        latency=Cell(None, None),
        disrupted=values.pop("disrupted", None),  # type: ignore[arg-type]
        **values,  # type: ignore[arg-type]
    )


def not_run_row(label: str) -> Row:
    return Row.not_run(label)


def lines(table: str) -> list[list[str]]:
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in table.splitlines()]


def test_two_backends_with_numbers_and_one_not_run() -> None:
    table = render_table([run_row("Alpha"), run_row("Beta"), not_run_row("Gamma")])

    rows = {cells[0]: cells for cells in lines(table)[2:] if cells[0] in {"Alpha", "Beta", "Gamma"}}
    head = lines(table)[0]
    assert rows["Alpha"][head.index("E1 recall")] == "0.833 / 0.500"
    assert rows["Alpha"][head.index("E3 violations per 100")] == "0.000 / 0.000"
    assert rows["Alpha"][head.index("E8 schema failure rate")] == "0.050 / 0.100"
    assert rows["Alpha"][head.index("Cost per run, USD")] == "0.0123 / 0.0200"
    assert all(cell == "not run" for cell in rows["Gamma"][2:-1] if cell not in {"-", ""})
    assert "0" not in "".join(rows["Gamma"][1:]).replace("not run", "")


def test_a_row_that_was_not_run_never_shows_zero() -> None:
    table = render_table([not_run_row("Gamma")])

    row = lines(table)[2]
    assert row[0] == "Gamma"
    assert row[1] == "not run"
    assert set(row[2:]) <= {"not run", "-"}


def test_a_metric_no_run_measured_is_not_run_even_in_a_run_row() -> None:
    table = render_table([run_row("Alpha")])

    head = lines(table)[0]
    assert lines(table)[2][head.index("E6 worst class max abs shift")] == "not run"
    assert lines(table)[2][head.index("Median latency")] == "not recorded"


def test_rows_with_the_same_prompt_and_fixtures_are_one_group() -> None:
    table = render_table([run_row("Alpha"), run_row("Beta")])

    head = lines(table)[0]
    assert [
        lines(table)[2][head.index("Conditions")],
        lines(table)[3][head.index("Conditions")],
    ] == [
        "A",
        "A",
    ]
    assert "same prompt hash and fixture set" in table
    assert "not comparable" not in table


def test_rows_with_different_prompt_hashes_are_marked_not_comparable() -> None:
    table = render_table([run_row("Alpha"), run_row("Beta", prompt="q" * 12)])

    head = lines(table)[0]
    conditions = [
        lines(table)[2][head.index("Conditions")],
        lines(table)[3][head.index("Conditions")],
    ]
    assert conditions == ["A", "B (not comparable with A)"]
    assert "not comparable" in table


def test_different_fixture_hashes_are_also_marked() -> None:
    table = render_table([run_row("Alpha"), run_row("Beta", fixture="z" * 12)])

    assert "B (not comparable with A)" in table


def test_with_no_run_at_all_the_note_says_so() -> None:
    table = render_table([not_run_row("Alpha"), not_run_row("Beta")])

    assert "No backend has been run yet" in table


def test_the_commit_and_hashes_are_listed_per_row() -> None:
    table = render_table([run_row("Alpha")])

    head = lines(table)[0]
    row = lines(table)[2]
    assert row[head.index("Commit")] == "a" * 12
    assert row[head.index("Prompt hash")] == "p" * 12
    assert row[head.index("Fixture hash")] == "f" * 12


def test_the_same_rows_always_render_the_same_text() -> None:
    rows = [run_row("Alpha"), not_run_row("Gamma")]

    assert render_table(rows) == render_table(rows)


def test_a_short_hash_is_a_stable_twelve_character_prefix() -> None:
    assert short_hash({"extract": "a" * 64, "entail": "b" * 64}) == short_hash(
        {"entail": "b" * 64, "extract": "a" * 64}
    )
    assert len(short_hash({"extract": "a" * 64})) == 12
    assert short_hash({"extract": "a" * 64}) != short_hash({"extract": "b" * 64})


def test_e6_shows_the_worst_class_shift_and_the_disrupted_count() -> None:
    table = render_table([run_row("Alpha", score_shift=scored(0.1, 0.4), disrupted=2)])

    head = lines(table)[0]
    row = lines(table)[2]
    assert row[head.index("E6 worst class max abs shift")] == "0.100 / 0.400"
    assert row[head.index("E6 disrupted")] == "2"


def test_e6_without_injection_results_says_not_run() -> None:
    table = render_table([run_row("Alpha")])

    head = lines(table)[0]
    row = lines(table)[2]
    assert row[head.index("E6 worst class max abs shift")] == "not run"
    assert row[head.index("E6 disrupted")] == "not run"
