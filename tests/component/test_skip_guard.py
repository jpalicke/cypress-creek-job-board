# ABOUTME: Checks that a skipped test turns the whole pytest session into a failure.
# ABOUTME: A missing service must never hide as a skip, so the guard fails the run loudly.
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

GUARD = (Path(__file__).parent.parent / "conftest.py").read_text(encoding="utf8")


def test_skipped_test_fails_the_session(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(GUARD)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.skip(reason="demo")
        def test_skipped():
            pass
        """
    )
    result = pytester.runpytest_subprocess()
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*skipped tests are not allowed*"])


def test_run_without_skips_passes(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(GUARD)
    pytester.makepyfile("def test_ok():\n    pass\n")
    result = pytester.runpytest_subprocess()
    assert result.ret == 0
