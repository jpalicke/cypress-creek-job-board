# ABOUTME: GET /api/health reports liveness and whether each configured backend answers.
# ABOUTME: Reachable means the backend address returned any HTTP answer within two seconds.
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from cypress_creek.config import ProviderSettings
from cypress_creek.providers.ollama import is_reachable

router = APIRouter()

Reachability = Literal["reachable", "unreachable", "not_checked"]


class BackendHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    reachable: Reachability


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"]
    backends: list[BackendHealth]


def check_reachability(settings: ProviderSettings) -> Reachability:
    """Only the Ollama adapter can be probed so far. Other backends report not_checked."""
    if settings.provider != "ollama":
        return "not_checked"
    return "reachable" if is_reachable(settings) else "unreachable"


@router.get("/api/health")
def get_health(request: Request) -> HealthResponse:
    settings: ProviderSettings | None = request.app.state.settings
    backends = []
    if settings is not None:
        backends.append(
            BackendHealth(
                provider=settings.provider,
                model=settings.model,
                reachable=check_reachability(settings),
            )
        )
    return HealthResponse(status="ok", backends=backends)
