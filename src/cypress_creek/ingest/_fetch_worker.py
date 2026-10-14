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
        pass_through = request.get("pass_through_statuses", False)
        if not isinstance(pass_through, bool):
            raise ValueError("pass_through_statuses must be a boolean")
        response = _fetch(
            request["url"],
            FetchLimits(**configuration),
            resolve=resolve,
            if_none_match=request.get("if_none_match"),
            pass_through_statuses=pass_through,
        )
        result = {
            "url": response.url,
            "status": response.status,
            "content_type": response.content_type,
            "body": base64.b64encode(response.body).decode("ascii"),
            "etag": response.etag,
            "retry_after": response.retry_after,
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
