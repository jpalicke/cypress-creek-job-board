# ABOUTME: Runs real loopback HTTP servers and the explicitly test-only transport worker.
# ABOUTME: Production fetching cannot select this resolver through arguments, config or environment.
import gzip
import socket
import socketserver
import struct
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import cast
from urllib.parse import urlsplit

from cypress_creek.ingest.url_guard import ValidatedTarget, validate_url


@dataclass
class Requests:
    received: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@contextmanager
def http_server() -> Iterator[tuple[int, Requests]]:
    requests = Requests()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                request = self.rfile.readline().decode("ascii").strip()
                if not request:
                    return
                _, path, _ = request.split(" ")
                headers: dict[str, str] = {}
                while line := self.rfile.readline().strip():
                    name, value = line.decode("ascii").split(":", 1)
                    headers[name.lower()] = value.strip()
                requests.received.append((path, headers))
                route = urlsplit(path).path
                body = b"public posting"
                fields = [("Content-Type", "text/plain")]
                status = "200 OK"
                if route.startswith("/redirect/"):
                    hops = int(route.rsplit("/", 1)[1])
                    location = f"/redirect/{hops - 1}" if hops > 1 else "/ok"
                    status = "302 Found"
                    fields += [("Location", location), ("Set-Cookie", "session=private")]
                elif route == "/private":
                    status = "302 Found"
                    fields.append(("Location", "http://169.254.169.254/secret"))
                elif route == "/bad-location":
                    status = "302 Found"
                    fields.append(("Location", "http://fixture.test/a b"))
                elif route == "/no-location":
                    status = "302 Found"
                elif route == "/wrong-type":
                    fields = [("Content-Type", "image/png")]
                elif route == "/missing-type":
                    fields = []
                elif route == "/error":
                    status = "500 Internal Server Error"
                    body = b"private server diagnostics"
                elif route == "/large":
                    body = b"x" * 65537
                elif route in {"/gzip", "/bomb", "/bad-gzip", "/short-gzip", "/two-gzip"}:
                    body = gzip.compress(b"x" * 200000 if route == "/bomb" else body)
                    fields.append(("Content-Encoding", "gzip"))
                    if route == "/bad-gzip":
                        body = b"not a gzip stream"
                    elif route == "/short-gzip":
                        body = body[:-4]
                    elif route == "/two-gzip":
                        body += gzip.compress(b"another member")
                elif route == "/encoding":
                    fields.append(("Content-Encoding", "br"))
                elif route == "/slow-headers":
                    time.sleep(5)
                if route == "/slow-headers-trickle":
                    for byte in b"HTTP/1.1 200 OK\r\n":
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.3)
                    return
                # Connection-close framing exercises the streamed cap without trusting a length.
                fields.append(("Connection", "close"))
                self.wfile.write(f"HTTP/1.1 {status}\r\n".encode())
                for name, value in fields:
                    self.wfile.write(f"{name}: {value}\r\n".encode())
                self.wfile.write(b"\r\n")
                if route == "/slow-body":
                    for _ in range(80):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.1)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Policy rejection and deadline cancellation intentionally close live sockets.
                pass
            except Exception as error:
                requests.failures.append(repr(error))

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = False
        allow_reuse_address = True

    with Server(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        try:
            yield int(server.server_address[1]), requests
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            assert not thread.is_alive()
            assert not requests.failures, requests.failures


def local_target(url: str) -> ValidatedTarget:
    """Permit only the named local fixture; every other URL gets production validation."""
    parsed = urlsplit(url)
    if parsed.hostname == "fixture.test" and parsed.scheme == "http" and parsed.port:
        return ValidatedTarget("http", "fixture.test", "127.0.0.1", parsed.port)
    return validate_url(url)


@contextmanager
def dns_rebind_server() -> Iterator[tuple[int, list[str]]]:
    """Answer real UDP DNS queries with a changed A record after the first query."""
    queries: list[str] = []
    failures: list[str] = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                packet, connection = cast(tuple[bytes, socket.socket], self.request)
                offset = 12
                labels: list[str] = []
                while packet[offset]:
                    length = packet[offset]
                    labels.append(packet[offset + 1 : offset + 1 + length].decode("ascii"))
                    offset += length + 1
                name = ".".join(labels)
                if packet[offset + 1 : offset + 5] != b"\x00\x01\x00\x01":
                    raise ValueError("Only A record questions are supported by this fixture")
                queries.append(name)
                ip = "127.0.0.1" if len(queries) == 1 else "127.0.0.2"
                header = packet[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
                question = packet[12 : offset + 5]
                answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 0, 4) + socket.inet_aton(ip)
                connection.sendto(header + question + answer, self.client_address)
            except Exception as error:
                failures.append(repr(error))

    class Server(socketserver.ThreadingUDPServer):
        daemon_threads = False
        allow_reuse_address = True

    with Server(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        try:
            yield int(server.server_address[1]), queries
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            assert not thread.is_alive()
            assert not failures, failures


def dns_lookup(host: str, port: int) -> str:
    """Make one actual UDP DNS A query to the local test responder."""
    labels = host.encode("ascii").split(b".")
    question = b"".join(bytes([len(label)]) + label for label in labels) + b"\x00\x00\x01\x00\x01"
    packet = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + question
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.settimeout(3)
        connection.sendto(packet, ("127.0.0.1", port))
        response, _ = connection.recvfrom(512)
    if response[:2] != packet[:2] or response[2:4] != b"\x81\x80":
        raise ValueError("Invalid DNS response from local test responder")
    answer_offset = 12 + len(question)
    if response[answer_offset : answer_offset + 12] != (
        b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 0, 4)
    ):
        raise ValueError("Unexpected DNS answer from local test responder")
    return socket.inet_ntoa(response[answer_offset + 12 : answer_offset + 16])


def dns_target(url: str, dns_port: int) -> ValidatedTarget:
    """Use local real DNS only for the named fixture; delegate other URLs to policy."""
    parsed = urlsplit(url)
    if parsed.hostname == "fixture.test" and parsed.scheme == "http" and parsed.port:
        return ValidatedTarget(
            "http", "fixture.test", dns_lookup("fixture.test", dns_port), parsed.port
        )
    return validate_url(url)


if __name__ == "__main__":
    from cypress_creek.ingest._fetch_worker import run_worker

    if sys.argv[1:] == ["--worker"]:
        run_worker(resolve=local_target)
    elif len(sys.argv) == 3 and sys.argv[1] == "--dns-worker":
        run_worker(resolve=partial(dns_target, dns_port=int(sys.argv[2])))
    else:
        raise SystemExit(2)
