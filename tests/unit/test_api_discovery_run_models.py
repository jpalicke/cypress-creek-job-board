# ABOUTME: Tests the request models of the discovery routes: strict fields, bounded cap, filters.
# ABOUTME: Unknown fields and out of range values are refused before any board is touched.
import pytest
from pydantic import ValidationError

from cypress_creek.api.schemas import DiscoveryRefreshRequest


def test_a_minimal_refresh_request_uses_the_default_cap_and_no_filters() -> None:
    request = DiscoveryRefreshRequest.model_validate({"backend": "ollama"})

    assert request.cap is None
    assert request.confirm_hosted is False
    assert request.filters.include_keywords == ()


def test_filters_are_the_same_filters_the_library_uses() -> None:
    request = DiscoveryRefreshRequest.model_validate(
        {"backend": "ollama", "filters": {"include_keywords": ["python"], "max_age_days": 30}}
    )

    assert request.filters.include_keywords == ("python",)
    assert request.filters.max_age_days == 30


@pytest.mark.parametrize(
    "body",
    [
        {"backend": "ollama", "surprise": 1},
        {"backend": "ollama", "cap": -1},
        {"backend": "ollama", "cap": 10_000},
        {"backend": "ollama", "filters": {"include_keywords": ["   "]}},
        {"backend": "ollama", "filters": {"max_age_days": 0}},
        {"backend": "ollama", "filters": {"apply": True}},
        {"backend": ""},
        {},
    ],
)
def test_bad_requests_are_refused(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DiscoveryRefreshRequest.model_validate(body)
