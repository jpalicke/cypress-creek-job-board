# ABOUTME: Typed errors raised while loading the fact bank.
# ABOUTME: FactValidationError names the fact and field, BankLoadError covers file level problems.


class BankLoadError(Exception):
    """The bank file could not be read or parsed as a bank."""


class FactValidationError(Exception):
    """A fact broke a bank rule. Names the fact, the field and the reason."""

    def __init__(self, fact_id: str, field: str, reason: str) -> None:
        super().__init__(f"{fact_id}: {field}: {reason}")
        self.fact_id = fact_id
        self.field = field
        self.reason = reason
