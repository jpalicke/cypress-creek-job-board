# ABOUTME: Verifies the production fetch entry against real public HTTPS and URL policy.
# ABOUTME: Network failures remain test failures instead of skipped or substituted responses.
from urllib.parse import urlsplit

import pytest

from cypress_creek.ingest.safe_http import fetch_url
from cypress_creek.ingest.url_guard import UrlGuardError


@pytest.mark.needs_network
def test_public_https_uses_original_hostname_with_verified_tls() -> None:
    response = fetch_url("https://example.com/")
    assert response.status == 200
    assert response.content_type == "text/html"
    assert urlsplit(response.url).hostname == "example.com"
    assert urlsplit(response.url).scheme == "https"
    assert b"<title>Example Domain</title>" in response.body


def test_production_fetch_refuses_loopback_before_http() -> None:
    with pytest.raises(UrlGuardError) as caught:
        fetch_url("http://127.0.0.1/")
    assert caught.value.reason_code == "unsafe_address"
    assert "127.0.0.1" not in str(caught.value)
