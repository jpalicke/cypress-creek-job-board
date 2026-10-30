# ABOUTME: What the routes share: the settings, the provider, the bank path and the lazy database.
# ABOUTME: The database is created and migrated on first use, so building the app touches no disk.
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from cypress_creek.config import ProviderSettings
from cypress_creek.providers.base import Provider
from cypress_creek.storage.repository import prepare_database


@dataclass
class Database:
    path: Path
    _ready: bool = field(default=False, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def ready(self) -> Path:
        """The database path, after the file exists and every migration has been applied."""
        with self._lock:
            if not self._ready:
                prepare_database(self.path)
                self._ready = True
        return self.path


@dataclass(frozen=True)
class Backend:
    settings: ProviderSettings
    provider: Provider


def database_of(request: Request) -> Path:
    database: Database = request.app.state.database
    return database.ready()


def backend_of(request: Request) -> Backend | None:
    backend: Backend | None = request.app.state.backend
    return backend


def bank_path_of(request: Request) -> Path:
    path: Path = request.app.state.bank_path
    return path


DatabasePath = Annotated[Path, Depends(database_of)]
BankPath = Annotated[Path, Depends(bank_path_of)]
