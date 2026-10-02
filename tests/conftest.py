# ABOUTME: Shared pytest hooks for every test tier.
# ABOUTME: Fails the session when any test is skipped so a missing service cannot hide.
import pytest


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    skipped = terminalreporter.stats.get("skipped", [])
    if skipped:
        terminalreporter.write_line(f"{len(skipped)} skipped tests are not allowed", red=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None and reporter.stats.get("skipped"):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
