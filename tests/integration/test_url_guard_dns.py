# ABOUTME: Runs the URL guard against public DNS using the real operating system resolver.
# ABOUTME: Resolver failures are typed errors and public DNS targets retain their original host.
import ipaddress
import traceback

import pytest

from cypress_creek.ingest.url_guard import UrlGuardError, validate_url

pytestmark = pytest.mark.needs_network


@pytest.mark.parametrize("host", ["example.com", "EXAMPLE.COM."])
def test_public_hostname_resolves_to_a_public_target(host: str) -> None:
    target = validate_url(f"https://{host}/")
    address = ipaddress.ip_address(target.ip)
    assert target.host == "example.com"
    assert target.scheme == "https"
    assert target.port == 443
    assert address.is_global
    assert not address.is_multicast
    assert not address.is_reserved


def test_failed_dns_does_not_echo_the_requested_hostname() -> None:
    hostname = "private-posting-reference.invalid"
    with pytest.raises(UrlGuardError) as caught:
        validate_url(f"https://{hostname}/")

    assert caught.value.reason_code == "dns_failure"
    assert hostname not in "".join(traceback.format_exception(caught.value))
