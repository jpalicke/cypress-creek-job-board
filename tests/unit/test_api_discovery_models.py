# ABOUTME: Tests the request models of the watchlist and blacklist routes, with no app or database.
# ABOUTME: A watchlist add needs the human approval marker, and unknown fields are refused.
import pytest
from pydantic import ValidationError

from cypress_creek.api.routes.blacklist import BlacklistRequest
from cypress_creek.api.routes.watchlist import WatchlistRequest
from cypress_creek.discovery.blacklist import BlockReason


def watch(**changes: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "display_name": "Acme Corp",
        "ats": "greenhouse",
        "slug": "acme",
        "identity_evidence": "strong",
        "approval": "human_confirmed",
    }
    fields.update(changes)
    return fields


def test_a_complete_request_is_accepted() -> None:
    request = WatchlistRequest.model_validate(watch())
    assert request.display_name == "Acme Corp"
    assert request.identity_evidence.value == "strong"


@pytest.mark.parametrize("marker", ["", "model", "human", "HUMAN_CONFIRMED", None, True])
def test_a_missing_or_wrong_approval_marker_is_refused(marker: object) -> None:
    with pytest.raises(ValidationError):
        WatchlistRequest.model_validate(watch(approval=marker))


def test_a_request_without_the_marker_is_refused() -> None:
    body = watch()
    del body["approval"]
    with pytest.raises(ValidationError):
        WatchlistRequest.model_validate(body)


@pytest.mark.parametrize(
    "extra", [{"proposed_by": "ollama:x"}, {"company_key": "acme"}, {"state": "approved"}]
)
def test_a_model_originated_or_derived_field_is_refused(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WatchlistRequest.model_validate(watch(**extra))


@pytest.mark.parametrize(
    "changes",
    [
        {"display_name": ""},
        {"display_name": "   "},
        {"display_name": "x" * 201},
        {"ats": ""},
        {"slug": " "},
        {"slug": "s" * 201},
        {"identity_evidence": "certain"},
    ],
)
def test_bad_fields_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WatchlistRequest.model_validate(watch(**changes))


def test_a_hostile_name_is_just_text() -> None:
    request = WatchlistRequest.model_validate(watch(display_name="<script>alert(1)</script>"))
    assert request.display_name == "<script>alert(1)</script>"


def test_a_blacklist_request_names_a_kind_a_value_and_a_reason() -> None:
    request = BlacklistRequest.model_validate(
        {"match_kind": "domain", "value": "example.com", "reason": "not a fit"}
    )
    assert request.match_kind is BlockReason.DOMAIN


@pytest.mark.parametrize(
    "changes",
    [
        {"match_kind": "name"},
        {"value": ""},
        {"value": "v" * 501},
        {"reason": ""},
        {"reason": "r" * 1001},
        {"extra": 1},
    ],
)
def test_a_bad_blacklist_request_is_refused(changes: dict[str, object]) -> None:
    body: dict[str, object] = {"match_kind": "slug", "value": "acme", "reason": "no"}
    body.update(changes)
    with pytest.raises(ValidationError):
        BlacklistRequest.model_validate(body)
