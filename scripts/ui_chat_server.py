# ABOUTME: A tiny real loopback chat server for the UI end to end tests, with hand written replies.
# ABOUTME: Draft requests get one clean and one flawed bullet; every other request gets a 503.
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 5319
CLEAN = "Backend Developer at Gravy Boat Labs, where I built and ran Python services."
FLAWED = "I led a team of 40 engineers."
DRAFT = {
    "schema_version": 1,
    "sentences": [
        {"text": CLEAN, "fact_ids": ["F-0001"]},
        {"text": FLAWED, "fact_ids": ["F-0001"]},
    ],
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self._send(200, {"ok": True})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = self.rfile.read(length).decode("utf-8", errors="replace")
        if '"DraftOutput"' not in request:
            self._send(503, {"error": "this test server only drafts"})
            return
        choice = {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(DRAFT)},
        }
        self._send(
            200, {"choices": [choice], "usage": {"prompt_tokens": 50, "completion_tokens": 30}}
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
