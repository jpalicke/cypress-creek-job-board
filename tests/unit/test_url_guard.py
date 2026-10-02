# ABOUTME: Exercises hostile URL syntax and public-address validation without a network.
# ABOUTME: Property tests cover both IP families and require safe, typed rejections.
import ipaddress
from dataclasses import FrozenInstanceError

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cypress_creek.ingest.url_guard import (
    UrlGuardError,
    ValidatedTarget,
    _authority,
    _validate_addresses,
    validate_url,
)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://127.0.0.1/", "unsafe_address"),
        ("http://10.0.0.1/", "unsafe_address"),
        ("http://172.16.0.1/", "unsafe_address"),
        ("http://192.168.0.1/", "unsafe_address"),
        ("http://169.254.169.254/", "unsafe_address"),
        ("http://0.0.0.0/", "unsafe_address"),
        ("http://100.64.0.1/", "unsafe_address"),
        ("http://224.0.0.1/", "unsafe_address"),
        ("http://240.0.0.1/", "unsafe_address"),
        ("http://192.0.2.1/", "unsafe_address"),
        ("http://[::1]/", "unsafe_address"),
        ("http://[::]/", "unsafe_address"),
        ("http://[fc00::1]/", "unsafe_address"),
        ("http://[fec0::1]/", "unsafe_address"),
        ("http://[fe80::1]/", "unsafe_address"),
        ("http://[ff02::1]/", "unsafe_address"),
        ("http://[2001:db8::1]/", "unsafe_address"),
        ("http://[::ffff:127.0.0.1]/", "unsafe_address"),
        ("http://[::ffff:8.8.8.8]/", "unsafe_address"),
        ("http://[2002:0808:0808::1]/", "unsafe_address"),
        ("http://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/", "unsafe_address"),
        ("http://[64:ff9b::808:808]/", "unsafe_address"),
        ("http://[fe80::1%25eth0]/", "ambiguous_host"),
        ("http://2130706433/", "ambiguous_host"),
        ("http://0177.0.0.1/", "ambiguous_host"),
        ("http://0x7f000001/", "ambiguous_host"),
        ("http://127.1/", "ambiguous_host"),
        ("http://0x7f.0.0.1/", "ambiguous_host"),
        ("http://127.0.0.1./", "ambiguous_host"),
        ("http://999.999.999.999/", "ambiguous_host"),
        ("http://localhost/", "unsafe_address"),
        ("http://api.LOCALHOST./", "unsafe_address"),
        ("ftp://8.8.8.8/", "unsupported_scheme"),
        ("file:///etc/passwd", "unsupported_scheme"),
        # Fictional credentials exercise rejection; this URL is never fetched.
        ("http://user:secret@8.8.8.8/", "credentials"),  # pragma: allowlist secret
        ("http://@8.8.8.8/", "credentials"),
        ("http://8.8.8.8:8080/", "unsupported_port"),
        ("http://8.8.8.8:0/", "unsupported_port"),
        ("http://8.8.8.8:65536/", "unsupported_port"),
        ("http://8.8.8.8:abc/", "unsupported_port"),
        ("http://8.8.8.8:/", "unsupported_port"),
        ("http://8.8.8.8:080/", "unsupported_port"),
        ("", "invalid_url"),
        ("https:///8.8.8.8/", "invalid_url"),
        ("https://", "invalid_url"),
        (" https://8.8.8.8/", "invalid_url"),
        ("http://8.8.8.8/\n", "invalid_url"),
        ("http://8.8.8.8/\x00", "invalid_url"),
        ("http://8.8.8.8/\x7f", "invalid_url"),
        ("http://8.8.8.8/hello world", "invalid_url"),
        ("http://8.8.8.8\\@127.0.0.1/", "invalid_url"),
        ("http://[::1", "invalid_url"),
        ("http://[8.8.8.8]/", "invalid_url"),
        ("http://[v1.localhost]/", "invalid_url"),
        ("http://8.8.8.8:443:80/", "invalid_url"),
        ("http://[2606:4700:4700::1111]suffix/", "invalid_url"),
        ("http://8.8.8.8]/", "invalid_url"),
        ("http://8.8.8.8%00/", "ambiguous_host"),
        ("http://%31%32%37.0.0.1/", "ambiguous_host"),
        ("http://example..com/", "ambiguous_host"),
        ("http://example.com../", "ambiguous_host"),
        ("http://-bad.example/", "ambiguous_host"),
        ("http://bad-.example/", "ambiguous_host"),
        ("http://bad_name.example/", "ambiguous_host"),
        ("http://\u00e9xample.com/", "ambiguous_host"),
        ("http://\u212a.example/", "ambiguous_host"),
        ("http://xn--xample-9ua.com/", "ambiguous_host"),
        ("http://" + "a" * 64 + ".example/", "ambiguous_host"),
        ("http://" + ".".join(["a" * 63] * 4) + "/", "ambiguous_host"),
    ],
)
def test_hostile_urls_are_rejected_with_a_stable_reason(url: str, reason: str) -> None:
    with pytest.raises(UrlGuardError) as caught:
        validate_url(url)
    assert caught.value.reason_code == reason
    assert str(caught.value) == "URL rejected by the network safety policy"
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://8.8.8.8/jobs", ValidatedTarget("http", "8.8.8.8", "8.8.8.8", 80)),
        ("HTTPS://1.1.1.1/", ValidatedTarget("https", "1.1.1.1", "1.1.1.1", 443)),
        ("http://8.8.8.8:443/", ValidatedTarget("http", "8.8.8.8", "8.8.8.8", 443)),
        ("https://8.8.8.8:80/", ValidatedTarget("https", "8.8.8.8", "8.8.8.8", 80)),
        (
            "https://[2606:4700:4700:0:0:0:0:1111]/",
            ValidatedTarget("https", "2606:4700:4700::1111", "2606:4700:4700::1111", 443),
        ),
        (
            "https://8.8.8.8/jobs?q=remote%20work#openings",
            ValidatedTarget("https", "8.8.8.8", "8.8.8.8", 443),
        ),
    ],
)
def test_public_literals_produce_an_immutable_connection_target(
    url: str, expected: ValidatedTarget
) -> None:
    target = validate_url(url)
    assert target == expected
    with pytest.raises(FrozenInstanceError):
        target.ip = "127.0.0.1"  # type: ignore[misc]


@given(st.ip_addresses(v=4))
def test_ipv4_literals_accept_exactly_global_unicast(address: ipaddress.IPv4Address) -> None:
    safe = address.is_global and not address.is_multicast and not address.is_reserved
    if safe:
        assert validate_url(f"https://{address}/").ip == str(address)
    else:
        with pytest.raises(UrlGuardError) as caught:
            validate_url(f"https://{address}/")
        assert caught.value.reason_code == "unsafe_address"


@given(st.ip_addresses(v=6))
def test_every_accepted_ipv6_literal_is_public_unicast(address: ipaddress.IPv6Address) -> None:
    try:
        target = validate_url(f"https://[{address}]/")
    except UrlGuardError as error:
        assert error.reason_code == "unsafe_address"
        return
    assert target.ip == str(address)
    assert address.is_global
    assert not address.is_multicast
    assert not address.is_reserved
    assert not address.is_site_local
    assert address.ipv4_mapped is None
    assert address.sixtofour is None
    assert address.teredo is None
    assert address not in ipaddress.IPv6Network("64:ff9b::/96")


@given(st.text(max_size=150))
def test_arbitrary_input_never_leaks_parser_exceptions(raw: str) -> None:
    # A missing authority prevents arbitrary text from invoking the resolver.
    with pytest.raises(UrlGuardError):
        validate_url("https:///" + raw)


@pytest.mark.parametrize(
    ("addresses", "reason"),
    [
        ([], "dns_failure"),
        (["8.8.8.8", "127.0.0.1"], "unsafe_address"),
        (["127.0.0.1", "8.8.8.8"], "unsafe_address"),
        (["8.8.8.8", "::1"], "unsafe_address"),
        (["2606:4700:4700::1111", "169.254.169.254"], "unsafe_address"),
        (["8.8.8.8", "::ffff:8.8.8.8"], "unsafe_address"),
        (["8.8.8.8", "malformed"], "dns_failure"),
        (["8.8.8.8", "2606:4700:4700::1111%eth0"], "unsafe_address"),
    ],
)
def test_address_reducer_rejects_the_entire_set_if_any_answer_is_unsafe(
    addresses: list[str], reason: str
) -> None:
    # These are hostile inputs to a pure reducer, not replacements for a resolver.
    with pytest.raises(UrlGuardError) as caught:
        _validate_addresses(addresses)
    assert caught.value.reason_code == reason


def test_address_reducer_preserves_the_first_public_answer() -> None:
    assert _validate_addresses(["8.8.8.8", "2606:4700:4700::1111"]) == "8.8.8.8"


@pytest.mark.parametrize("authority", ["[v1.example.invalid]", "[v1.a:b]:443"])
def test_bracketed_future_address_cannot_be_treated_as_a_dns_name(authority: str) -> None:
    with pytest.raises(UrlGuardError) as caught:
        _authority(authority, "https")
    assert caught.value.reason_code == "invalid_url"
