# ABOUTME: Tests the rule that a hosted backend must be chosen and confirmed in the request.
# ABOUTME: A local backend needs only its name, so a hosted one can never be the silent default.
import pytest

from cypress_creek.api.backends import BackendChoiceError, check_backend_choice
from cypress_creek.providers.base import Capabilities, CostPerMtok


def capabilities(*, local: bool) -> Capabilities:
    return Capabilities(
        context_tokens=8192,
        strict_schema=True,
        local=local,
        cost_per_mtok=CostPerMtok(input=0 if local else 2, output=0 if local else 10),
    )


def test_the_configured_local_backend_is_accepted_by_name() -> None:
    check_backend_choice(
        "ollama", False, configured="ollama", capabilities=capabilities(local=True)
    )


def test_another_name_is_refused() -> None:
    with pytest.raises(BackendChoiceError) as caught:
        check_backend_choice(
            "anthropic", True, configured="ollama", capabilities=capabilities(local=True)
        )

    assert caught.value.code == "unknown_backend"


def test_a_hosted_backend_needs_explicit_confirmation() -> None:
    hosted = capabilities(local=False)
    with pytest.raises(BackendChoiceError) as caught:
        check_backend_choice("anthropic", False, configured="anthropic", capabilities=hosted)
    assert caught.value.code == "hosted_backend_not_confirmed"

    check_backend_choice("anthropic", True, configured="anthropic", capabilities=hosted)
