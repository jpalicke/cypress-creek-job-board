# ABOUTME: Combines real UDP DNS changes with a worker fetching from a real HTTP server.
# ABOUTME: The test-only resolver demonstrates pinning without replacing production DNS policy.
import sys
from pathlib import Path

from http_support import dns_lookup, dns_rebind_server, http_server

from cypress_creek.ingest.safe_http import FetchLimits, _run_worker


def test_worker_pins_first_dns_answer_without_resolving_again() -> None:
    with dns_rebind_server() as (dns_port, queries), http_server() as (http_port, requests):
        url = f"http://fixture.test:{http_port}/ok"
        command = [
            sys.executable,
            str(Path(__file__).parents[1] / "http_support.py"),
            "--dns-worker",
            str(dns_port),
        ]
        response = _run_worker(url, FetchLimits(), command)
        assert response.status == 200
        assert response.body == b"public posting"
        assert response.url == url
        assert queries == ["fixture.test"]
        assert len(requests.received) == 1
        path, headers = requests.received[0]
        assert path == "/ok"
        assert headers["host"] == f"fixture.test:{http_port}"

        # A subsequent real DNS query changes the answer, but the fetch needed only one.
        assert dns_lookup("fixture.test", dns_port) == "127.0.0.2"
        assert queries == ["fixture.test", "fixture.test"]
