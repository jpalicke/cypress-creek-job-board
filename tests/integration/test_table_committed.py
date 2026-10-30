# ABOUTME: Checks the committed results table against the committed run files in the repository.
# ABOUTME: Every metrics file must have its run file, and the README block must match the page.

from evals.harness.table import (
    DEFAULT_BACKENDS,
    DEFAULT_PAGE,
    DEFAULT_README,
    DEFAULT_RESULTS,
    README_END,
    README_START,
    collect_rows,
    load_targets,
    render_table,
)


def test_the_page_and_the_readme_block_hold_the_table_of_the_committed_results() -> None:
    rows = collect_rows(DEFAULT_RESULTS, load_targets(DEFAULT_BACKENDS))
    table = render_table(rows)

    assert table in DEFAULT_PAGE.read_text(encoding="utf-8")
    readme = DEFAULT_README.read_text(encoding="utf-8")
    block = readme[readme.index(README_START) : readme.index(README_END)]
    assert table in block


def test_a_backend_with_no_committed_run_says_not_run_never_zero() -> None:
    rows = collect_rows(DEFAULT_RESULTS, load_targets(DEFAULT_BACKENDS))

    for row in rows:
        if not row.was_run:
            assert row.recall.mean is None and row.cost.mean is None
