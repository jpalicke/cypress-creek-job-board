# ABOUTME: The uvicorn entry point. It binds to loopback on port 5309 and refuses any other host.
# ABOUTME: Run it with `uv run cypress-creek-api`. Provider settings come from config or env vars.
import os
import sqlite3
import sys

import uvicorn

from cypress_creek.api.app import create_app
from cypress_creek.api.security import API_PORT
from cypress_creek.config import ConfigError, load_settings
from cypress_creek.storage.db import MigrationError

HOST_ENV = "CYPRESS_CREEK_API_HOST"
DEFAULT_HOST = "127.0.0.1"


class RemoteBindRefused(ConfigError):
    """The API may only bind to a loopback address."""


def check_bind_host(host: str) -> str:
    """Only 127.0.0.1. Another loopback name would bind, then fail every Host check."""
    if host != DEFAULT_HOST:
        raise RemoteBindRefused(f"the API only binds to the loopback address {DEFAULT_HOST}")
    return host


def main() -> int:
    try:
        host = check_bind_host(os.environ.get(HOST_ENV, "").strip() or DEFAULT_HOST)
        app = create_app(load_settings())
    except ConfigError as error:
        print(f"cypress-creek-api: {error}", file=sys.stderr)
        return 2
    try:
        app.state.database.ready()
    except (MigrationError, sqlite3.Error, OSError) as error:
        print(f"cypress-creek-api: the database could not be prepared: {error}", file=sys.stderr)
        return 2
    uvicorn.run(app, host=host, port=API_PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
