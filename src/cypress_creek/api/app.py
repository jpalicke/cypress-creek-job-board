# ABOUTME: The app factory. It wires the headers, Host check, CSRF check, typed errors and routes.
# ABOUTME: No CORS middleware is ever added, and the interactive docs and schema routes are off.
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from cypress_creek.api.context import Backend, Database
from cypress_creek.api.errors import install_error_handlers
from cypress_creek.api.routes import (
    blacklist,
    discovery,
    facts,
    health,
    postings,
    providers,
    reports,
    session,
    suggestions,
    watchlist,
)
from cypress_creek.api.routes.providers import CostResponse, ProviderInfo
from cypress_creek.api.security import (
    API_PORT,
    MAX_BODY_BYTES,
    MAX_PDF_BYTES,
    BodyLimitMiddleware,
    CsrfMiddleware,
    HostCheckMiddleware,
    SecurityHeadersMiddleware,
    allowed_hosts,
    new_token,
)
from cypress_creek.config import ProviderSettings
from cypress_creek.discovery.adapters.base import BoardAdapter
from cypress_creek.facts.loader import bank_path as default_bank_path
from cypress_creek.providers import get_provider
from cypress_creek.storage.db import database_path as default_database_path

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"


def describe_provider(backend: Backend) -> ProviderInfo:
    capabilities = backend.provider.capabilities
    return ProviderInfo(
        provider=backend.settings.provider,
        model=backend.settings.model,
        local=capabilities.local,
        strict_schema=capabilities.strict_schema,
        context_tokens=capabilities.context_tokens,
        cost_per_mtok=CostResponse(
            input=capabilities.cost_per_mtok.input, output=capabilities.cost_per_mtok.output
        ),
    )


def create_app(
    settings: ProviderSettings | None,
    *,
    static_dir: Path | None = DEFAULT_STATIC_DIR,
    database_path: Path | None = None,
    bank_path: Path | None = None,
    adapters: Mapping[str, BoardAdapter] | None = None,
) -> FastAPI:
    """Build the app. Every call makes a fresh CSRF token, so each server start has its own.

    The database file is created and migrated on first use, and the bank file is read on each
    request, so an edit to it takes effect without a restart. `adapters` are the board adapters
    discovery fetches with; None means the real ones, built on first use."""
    app = FastAPI(
        title="Cypress Creek",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    backend = Backend(settings, get_provider(settings)) if settings is not None else None
    app.state.settings = settings
    app.state.backend = backend
    app.state.csrf_token = new_token()
    app.state.providers = [describe_provider(backend)] if backend is not None else []
    app.state.database = Database(database_path or default_database_path())
    app.state.bank_path = bank_path or default_bank_path()
    app.state.adapters = dict(adapters) if adapters is not None else None
    install_error_handlers(app)
    for module in (
        health,
        providers,
        session,
        postings,
        reports,
        facts,
        suggestions,
        watchlist,
        blacklist,
        discovery,
    ):
        app.include_router(module.router)
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    # The last one added is the outermost: headers wrap everything, then the Host check, then
    # the body limit, then CSRF.
    app.add_middleware(CsrfMiddleware, token=app.state.csrf_token)
    app.add_middleware(BodyLimitMiddleware, default_limit=MAX_BODY_BYTES, pdf_limit=MAX_PDF_BYTES)
    app.add_middleware(HostCheckMiddleware, allowed=allowed_hosts(API_PORT))
    app.add_middleware(SecurityHeadersMiddleware)
    return app
