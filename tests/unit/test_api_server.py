# ABOUTME: Unit tests for the server's bind rule: it binds to 127.0.0.1 and nothing else.
# ABOUTME: Other loopback names would only fail the Host check later, so they are refused up front.
import pytest

from cypress_creek.api.server import RemoteBindRefused, check_bind_host


def test_the_loopback_address_is_accepted() -> None:
    assert check_bind_host("127.0.0.1") == "127.0.0.1"


@pytest.mark.parametrize(
    "host", ["127.0.0.2", "::1", "localhost", "0.0.0.0", "::", "192.168.1.5", "example.com", ""]
)
def test_anything_else_is_refused(host: str) -> None:
    with pytest.raises(RemoteBindRefused, match="127.0.0.1"):
        check_bind_host(host)
