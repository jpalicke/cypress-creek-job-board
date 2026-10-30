# ABOUTME: Imports a resume through the real API server with the model backend unreachable.
# ABOUTME: The answer is a typed not_run with no candidates, and nothing reaches the bank.
from pathlib import Path

from api_server_support import call, running_server

RESUME = (Path(__file__).parent.parent / "fixtures" / "resume" / "fictional_resume.txt").read_text(
    encoding="utf-8"
)


def test_an_unreachable_backend_gives_a_typed_answer_and_no_candidates(tmp_path: Path) -> None:
    bank = tmp_path / "private" / "bank.yaml"
    with running_server(tmp_path, bank):
        _, session = call("GET", "/api/session")
        token = session["csrf_token"]  # type: ignore[index]

        status, answer = call(
            "POST", "/api/import/resume", {"text": RESUME, "backend": "ollama"}, token
        )
        assert status == 200
        assert answer["status"] == "not_run"  # type: ignore[index]
        assert answer["candidates"] == [] and answer["failure"]  # type: ignore[index]

        assert call("GET", "/api/import/candidates")[1] == {"candidates": []}
        assert call("POST", "/api/import/resume", {"text": RESUME, "backend": "ollama"})[0] == 403
        assert call("GET", "/api/facts")[0] == 404

    assert not bank.exists()
