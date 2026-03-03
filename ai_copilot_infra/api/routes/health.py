"""
Health-check endpoint.
Used by Docker / load-balancers to verify liveness and readiness.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from ai_copilot_infra.core.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str
    env: str


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        env=settings.app_env,
    )
