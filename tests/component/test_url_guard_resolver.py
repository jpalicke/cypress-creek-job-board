# ABOUTME: Exercises URL validation with the machine's real resolver and socket address parser.
# ABOUTME: Local hostname resolution must fail closed and public targets must retain usable IPs.
import ipaddress
import socket

import pytest

from cypress_creek.ingest.url_guard import UrlGuardError, validate_url


def test_machine_hostname_cannot_hide_a_local_address() -> None:
    hostname = socket.gethostname()
    addresses = socket.getaddrinfo(hostname, 80, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    assert any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses)

    with pytest.raises(UrlGuardError) as caught:
        validate_url(f"http://{hostname}/")

    assert caught.value.reason_code == "unsafe_address"


@pytest.mark.parametrize(
    ("url", "family"),
    [
        ("http://1.1.1.1/", socket.AF_INET),
        ("https://[2606:4700:4700::1111]/", socket.AF_INET6),
    ],
)
def test_validated_ip_is_usable_without_a_hostname_lookup(url: str, family: int) -> None:
    target = validate_url(url)
    packed = socket.inet_pton(family, target.ip)
    assert socket.inet_ntop(family, packed) == target.ip
    addresses = socket.getaddrinfo(
        target.ip,
        target.port,
        family=family,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
        flags=socket.AI_NUMERICHOST,
    )
    assert addresses
    assert all(row[4][0] == target.ip and row[4][1] == target.port for row in addresses)
