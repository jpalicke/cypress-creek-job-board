# ABOUTME: The app factory. It wires the Host check, the CSRF dependency, typed errors and routes.
# ABOUTME: No CORS middleware is ever added, and the interactive docs and schema routes are off.
from pathlib import Path

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from cypress_creek.api.errors import install_error_handlers
from cypress_creek.api.routes import health, providers, session
from cypress_creek.api.routes.providers import CostResponse, ProviderInfo
from cypress_creek.api.security import (
    API_PORT,
    CsrfMiddleware,
    HostCheckMiddleware,
    SecurityHeadersMiddleware,
    allowed_hosts,
    new_token,
)
from cypress_creek.config import ProviderSettings
from cypress_creek.providers import get_provider

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"


def describe_provider(settings: ProviderSettings) -> ProviderInfo:
    capabilities = get_provider(settings).capabilities
    return ProviderInfo(
        provider=settings.provider,
        model=settings.model,
        local=capabilities.local,
        strict_schema=capabilities.strict_schema,
        context_tokens=capabilities.context_tokens,
        cost_per_mtok=CostResponse(
            input=capabilities.cost_per_mtok.input, output=capabilities.cost_per_mtok.output
        ),
    )


def create_app(
    settings: ProviderSettings | None, *, static_dir: Path | None = DEFAULT_STATIC_DIR
) -> FastAPI:
    """Build the app. Every call makes a fresh CSRF token, so each server start has its own."""
    app = FastAPI(
        title="Cypress Creek",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.csrf_token = new_token()
    app.state.providers = [describe_provider(settings)] if settings is not None else []
    install_error_handlers(app)
    for module in (health, providers, session):
        app.include_router(module.router)
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    # The last one added is the outermost. Headers wrap everything, then the Host check, then CSRF.
    app.add_middleware(CsrfMiddleware, token=app.state.csrf_token)
    app.add_middleware(HostCheckMiddleware, allowed=allowed_hosts(API_PORT))
    app.add_middleware(SecurityHeadersMiddleware)
    return app
