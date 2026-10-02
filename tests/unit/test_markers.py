# ABOUTME: Checks that the live and needs_network markers are registered under strict markers.
# ABOUTME: An unregistered marker would error at collection, so collection itself is the proof.
import pytest


@pytest.mark.live
def test_live_marker_is_registered() -> None:
    assert True


@pytest.mark.needs_network
def test_needs_network_marker_is_registered() -> None:
    assert True
