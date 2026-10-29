# ABOUTME: GET /api/providers lists the configured backend and what it can do, never any key.
# ABOUTME: The data comes from the provider's own capabilities, built once when the app starts.
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class CostResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input: float
    output: float


class ProviderInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    local: bool
    strict_schema: bool
    context_tokens: int
    cost_per_mtok: CostResponse


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    providers: list[ProviderInfo]


@router.get("/api/providers")
def list_providers(request: Request) -> ProvidersResponse:
    providers: list[ProviderInfo] = request.app.state.providers
    return ProvidersResponse(providers=providers)
