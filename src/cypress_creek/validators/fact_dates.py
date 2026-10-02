# ABOUTME: Validator V12 date sanity for a fact, wrapping the one shared date rule set.
# ABOUTME: The loader calls the same rules, so bad bank data is caught at load and again here.
from datetime import date

from cypress_creek.facts.dates import date_problems
from cypress_creek.facts.models import Fact
from cypress_creek.validators.verdict import Verdict, fail, ok


def check_fact_dates(fact: Fact, today: date) -> Verdict:
    """V12: fact dates are not in the future and the start does not follow the end."""
    problems = date_problems(fact.start, fact.end, fact.verified_on, today)
    if problems:
        field, reason = problems[0]
        return fail("V12", f"{fact.id} {field}: {reason}", field)
    return ok("V12")
