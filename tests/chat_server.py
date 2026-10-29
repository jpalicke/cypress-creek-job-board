# ABOUTME: A real loopback HTTP server that answers chat completion requests with set replies.
# ABOUTME: Test only. It records each request so tests can check the path, headers and JSON body.
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Reply:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Recorded:
    path: str
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body)


def json_reply(value: object, status: int = 200, **headers: str) -> Reply:
    return Reply(status, json.dumps(value).encode("utf-8"), dict(headers))


@contextmanager
def chat_server(reply: Reply) -> Iterator[tuple[str, list[Recorded]]]:
    """Serve `reply` to every POST. Yields the base URL (ending in /v1) and the request log."""
    log: list[Recorded] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            log.append(
                Recorded(
                    self.path,
                    {name.lower(): value for name, value in self.headers.items()},
                    self.rfile.read(length),
                )
            )
            self.send_response(reply.status)
            for name, value in reply.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", log
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
