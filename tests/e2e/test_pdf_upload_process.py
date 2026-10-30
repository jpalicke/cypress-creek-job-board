# ABOUTME: Uploads hostile PDFs to the real API server process and reads the answers back.
# ABOUTME: Hidden text never reaches the stored posting, and the server survives a bomb.
import http.client
import json
from pathlib import Path

from api_server_support import PORT, call, running_server

FOLDER = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "pdf"


def upload(token: str, name: str) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    try:
        connection.request(
            "POST",
            "/api/postings",
            body=(FOLDER / name).read_bytes(),
            headers={"Content-Type": "application/pdf", "X-CSRF-Token": token},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_hostile_pdfs_through_the_real_server(tmp_path: Path) -> None:
    with running_server(tmp_path):
        _, session = call("GET", "/api/session")
        token = session["csrf_token"]  # type: ignore[index]

        status, clean = upload(token, "clean.pdf")
        assert status == 201 and str(clean["text"]).startswith("Senior Data Engineer")

        status, hidden = upload(token, "white_on_white.pdf")
        assert status == 201
        assert "ZXQ-PAYLOAD" not in str(hidden["text"])
        assert hidden["extraction_warnings"] == [{"kind": "hidden_white_text", "count": 1}]

        status, bomb = upload(token, "decompression_bomb.pdf")
        assert status == 422
        assert bomb["error"]["code"] == "pdf_resource_limit"  # type: ignore[index]

        status, encrypted = upload(token, "encrypted.pdf")
        assert status == 422 and encrypted["error"]["code"] == "pdf_encrypted"  # type: ignore[index]

        health_status, _ = call("GET", "/api/health")
        assert health_status == 200
