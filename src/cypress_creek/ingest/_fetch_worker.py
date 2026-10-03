# ABOUTME: Runs one bounded HTTP fetch and serializes only a result or redacted error.
# ABOUTME: The production entry point always applies the public URL validation policy.
import base64
import json
import sys
from collections.abc import Callable

from cypress_creek.ingest.safe_http import FetchLimits, SafeHttpError, _fetch
from cypress_creek.ingest.url_guard import UrlGuardError, ValidatedTarget, validate_url


def run_worker(resolve: Callable[[str], ValidatedTarget]) -> None:
    try:
        request = json.load(sys.stdin)
        configuration = request["limits"]
        configuration["content_types"] = frozenset(configuration["content_types"])
        response = _fetch(request["url"], FetchLimits(**configuration), resolve=resolve)
        result = {
            "url": response.url,
            "status": response.status,
            "content_type": response.content_type,
            "body": base64.b64encode(response.body).decode("ascii"),
        }
    except UrlGuardError as error:
        result = {"error": "url_guard", "reason": error.reason_code}
    except SafeHttpError as error:
        result = {"error": "safe_http", "reason": error.reason_code}
    except (ValueError, KeyError, TypeError):
        result = {"error": "safe_http", "reason": "network_error"}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    run_worker(validate_url)
