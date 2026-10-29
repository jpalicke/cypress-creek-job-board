# ABOUTME: The local HTTP API: a FastAPI app on loopback with Host, CSRF and typed error rules.
# ABOUTME: Import create_app to build the app. Routes live in the routes package.
from cypress_creek.api.app import create_app

__all__ = ["create_app"]
