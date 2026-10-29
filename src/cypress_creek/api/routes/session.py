# ABOUTME: GET /api/session hands the UI the per-session CSRF token. It sets no cookie.
# ABOUTME: The Host check keeps other sites from reaching it, and no CORS lets none read it.
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    csrf_token: str


@router.get("/api/session")
def get_session(request: Request) -> SessionResponse:
    return SessionResponse(csrf_token=request.app.state.csrf_token)
