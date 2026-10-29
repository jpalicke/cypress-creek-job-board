# ABOUTME: Checks in the real repository that every fixture's labels are committed and unchanged.
# ABOUTME: A run may only use labels that git already holds, so edits must be committed first.
from pathlib import Path

import pytest

from evals.harness.fixtures import discover_fixtures
from evals.harness.labels import require_committed_labels

FIXTURES = Path(__file__).parent.parent.parent / "evals" / "fixtures"
DIRECTORIES = discover_fixtures(FIXTURES)


@pytest.mark.parametrize("directory", DIRECTORIES, ids=[d.name for d in DIRECTORIES])
def test_the_labels_of_every_fixture_are_committed(directory: Path) -> None:
    require_committed_labels(directory)
