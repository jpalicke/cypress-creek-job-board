# ABOUTME: The backend choice rule for analysis: name the configured backend, confirm a hosted one.
# ABOUTME: A hosted backend can therefore never run just because it is the configured default.
from cypress_creek.providers.base import Capabilities


class BackendChoiceError(Exception):
    """The request's backend choice is not allowed. `code` is a stable API error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_backend_choice(
    requested: str, confirm_hosted: bool, *, configured: str, capabilities: Capabilities
) -> None:
    if requested != configured:
        raise BackendChoiceError("unknown_backend")
    if not capabilities.local and not confirm_hosted:
        raise BackendChoiceError("hosted_backend_not_confirmed")
