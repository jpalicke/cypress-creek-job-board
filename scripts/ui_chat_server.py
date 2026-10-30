# ABOUTME: A tiny real loopback chat server for the UI end to end tests, with hand written replies.
# ABOUTME: Draft requests get a clean and a flawed bullet, resume imports a fact per line, else 503.
import json
import re
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


RESUME = re.compile(r"<<<POSTING (\w+)>>>\n(.*)\n<<<END POSTING \1>>>", re.S)
INVENTED = {
    "claim": "Led 40 engineers.",
    "kind": "employment",
    "tags": [],
    "source": "Led 40 engineers",
}


def resume_reply(request: str) -> dict[str, object]:
    """One candidate per line of the resume, quoting it, plus one the resume cannot support."""
    user = json.loads(request)["messages"][1]["content"]
    found = RESUME.search(user)
    lines = [line for line in (found.group(2) if found else "").split("\n") if line.strip()]
    candidates: list[dict[str, object]] = [
        {"claim": line[:300], "kind": "employment", "tags": [], "source": line}
        for line in lines[:5]
    ]
    return {"schema_version": 1, "candidates": [*candidates, INVENTED]}


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
        if '"DraftOutput"' in request:
            answer: dict[str, object] = DRAFT
        elif '"ResumeImportOutput"' in request:
            answer = resume_reply(request)
        else:
            self._send(503, {"error": "this test server only drafts and imports"})
            return
        choice = {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(answer)},
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
