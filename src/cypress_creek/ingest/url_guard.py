# ABOUTME: Validates hostile URLs and every resolved address before selecting a public target.
# ABOUTME: Targets carry the pinned IP separately from the hostname needed for HTTP and TLS.
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

type ReasonCode = Literal[
    "invalid_url",
    "unsupported_scheme",
    "credentials",
    "unsupported_port",
    "ambiguous_host",
    "unsafe_address",
    "dns_failure",
]

_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_NUMERIC_HOST = re.compile(r"(?:[0-9]+|0x[0-9a-f]+)(?:\.(?:[0-9]+|0x[0-9a-f]+))*")
_IPV6_AUTHORITY = re.compile(r"\[([^\]]+)\](?::(.*))?")
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")


class UrlGuardError(Exception):
    """A stable rejection reason without hostile URL content or resolver details."""

    def __init__(self, reason_code: ReasonCode) -> None:
        super().__init__("URL rejected by the network safety policy")
        self.reason_code = reason_code


@dataclass(frozen=True)
class ValidatedTarget:
    """Connection coordinates; consumers must connect to ip without resolving host again."""

    scheme: str
    host: str
    ip: str
    port: int


def _check_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise UrlGuardError("unsafe_address")
    if isinstance(address, ipaddress.IPv6Address) and (
        address.scope_id is not None
        or address.is_site_local
        or address.ipv4_mapped is not None
        or address.sixtofour is not None
        or address.teredo is not None
        or address in _NAT64
    ):
        raise UrlGuardError("unsafe_address")


def _validate_addresses(addresses: list[str]) -> str:
    """Reject the complete answer set if any address is unsafe, before selecting one."""
    if not addresses:
        raise UrlGuardError("dns_failure")
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise UrlGuardError("dns_failure") from None
        _check_address(address)
    return str(ipaddress.ip_address(addresses[0]))


def _authority(authority: str, scheme: str) -> tuple[str, int]:
    if "@" in authority:
        raise UrlGuardError("credentials")
    if authority.startswith("["):
        match = _IPV6_AUTHORITY.fullmatch(authority)
        if match is None:
            raise UrlGuardError("invalid_url")
        raw_host, raw_port = match.groups()
        try:
            ipaddress.IPv6Address(raw_host)
        except ValueError:
            raise UrlGuardError("invalid_url") from None
    else:
        if authority.count(":") > 1 or "[" in authority or "]" in authority:
            raise UrlGuardError("invalid_url")
        raw_host, separator, port_text = authority.partition(":")
        raw_port = port_text if separator else None
    if not raw_host:
        raise UrlGuardError("invalid_url")
    if raw_port is not None and raw_port not in {"80", "443"}:
        raise UrlGuardError("unsupported_port")
    port = int(raw_port) if raw_port is not None else (443 if scheme == "https" else 80)
    return raw_host, port


def validate_url(url: str) -> ValidatedTarget:
    """Resolve once, validate all answers, and return public HTTP(S) coordinates.

    Only ports 80 and 443 are allowed. Credentials, whitespace, control characters,
    backslashes, scoped IPv6, and legacy numeric hosts are refused. DNS names use
    ASCII labels without IDNs; case and one trailing dot are normalized. IPv6
    mapped and transition addresses fail closed. No HTTP request is made here.
    The operating system controls the blocking resolver's timeout.
    """
    if not url or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        raise UrlGuardError("invalid_url")
    if "\\" in url:
        raise UrlGuardError("invalid_url")
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise UrlGuardError("invalid_url") from None
    if parsed.scheme not in {"http", "https"}:
        raise UrlGuardError("unsupported_scheme")
    raw_host, port = _authority(parsed.netloc, parsed.scheme)
    if not raw_host.isascii() or "%" in raw_host:
        raise UrlGuardError("ambiguous_host")
    try:
        literal = ipaddress.ip_address(raw_host)
    except ValueError:
        literal = None
    if literal is not None:
        _check_address(literal)
        return ValidatedTarget(parsed.scheme, str(literal), str(literal), port)

    host = raw_host.lower().removesuffix(".")
    if _NUMERIC_HOST.fullmatch(host):
        raise UrlGuardError("ambiguous_host")
    if len(host) > 253 or any(
        _DNS_LABEL.fullmatch(label) is None or label.startswith("xn--") for label in host.split(".")
    ):
        raise UrlGuardError("ambiguous_host")
    if host == "localhost" or host.endswith(".localhost"):
        raise UrlGuardError("unsafe_address")
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        raise UrlGuardError("dns_failure") from None
    addresses: list[str] = []
    for family, _, _, _, sockaddr in answers:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise UrlGuardError("dns_failure")
        addresses.append(str(sockaddr[0]))
    ip = _validate_addresses(addresses)
    return ValidatedTarget(parsed.scheme, host, ip, port)
