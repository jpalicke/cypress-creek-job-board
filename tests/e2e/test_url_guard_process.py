# ABOUTME: Exercises the public URL guard from a separate Python consumer process.
# ABOUTME: Verifies safe target handoff and redacted rejection without any test bypass or mocks.
import json
import subprocess
import sys

import pytest

CONSUMER = """
import json
import sys
from dataclasses import asdict
from cypress_creek.ingest.url_guard import UrlGuardError, validate_url

try:
    result = asdict(validate_url(sys.argv[1]))
except UrlGuardError as error:
    print(json.dumps({'reason_code': error.reason_code, 'message': str(error)}))
    raise SystemExit(2) from None
print(json.dumps(result))
"""


def test_consumer_receives_a_public_target() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CONSUMER, "https://1.1.1.1/"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "scheme": "https",
        "host": "1.1.1.1",
        "ip": "1.1.1.1",
        "port": 443,
    }


@pytest.mark.parametrize(
    ("url", "reason_code"),
    [
        ("http://169.254.169.254/latest/meta-data", "unsafe_address"),
        # Fictional credentials exercise redaction; this URL is never fetched.
        (
            "http://private-user:private-password@1.1.1.1/",  # pragma: allowlist secret
            "credentials",
        ),
    ],
)
def test_consumer_receives_a_typed_redacted_rejection(url: str, reason_code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", CONSUMER, url],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    assert result.stderr == ""
    error = json.loads(result.stdout)
    assert error["reason_code"] == reason_code
    assert "private-user" not in result.stdout
    assert "private-password" not in result.stdout
    assert url not in result.stdout
