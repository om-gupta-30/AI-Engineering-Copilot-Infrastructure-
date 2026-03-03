"""
FastAPI application factory.
All routers, middleware, and lifespan hooks are registered here.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_copilot_infra.api.middleware.logging import LoggingMiddleware
from ai_copilot_infra.api.routes import copilot, health
from ai_copilot_infra.core.config import settings
from ai_copilot_infra.infra.redis_client import close_pool, get_pool
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle hooks."""
    logger.info("Starting up AI Copilot Infra", version=settings.app_version, env=settings.app_env)

    # Initialise Redis connection pool eagerly so the first request doesn't pay
    get_pool()

    yield

    # Graceful shutdown — drain Redis connections
    await close_pool()
    logger.info("Shutting down AI Copilot Infra")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(copilot.router, prefix=settings.api_prefix)

    return app


app: FastAPI = create_app()
