# ABOUTME: Date sanity rules for facts: no future dates and a start that does not follow the end.
# ABOUTME: One source of truth, the loader and validator V12 both call date_problems.
from datetime import date


def date_problems(
    start: date | None, end: date | None, verified_on: date | None, today: date
) -> list[tuple[str, str]]:
    """Return (field, reason) for each date rule the given dates break."""
    problems: list[tuple[str, str]] = []
    for field, value in (("start", start), ("end", end), ("verified_on", verified_on)):
        if value is not None and value > today:
            problems.append((field, f"{value} is in the future"))
    if start is not None and end is not None and start > end:
        problems.append(("start", f"start {start} is after end {end}"))
    return problems
