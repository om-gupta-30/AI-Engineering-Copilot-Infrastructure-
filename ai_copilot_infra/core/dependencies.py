"""
FastAPI dependency injection providers.

Singletons are created once at first resolution and cached for the
application lifetime via @lru_cache.  Each provider is exposed as a
typed Annotated alias so endpoints declare deps with zero boilerplate:

    async def my_endpoint(workflow: WorkflowDep) -> ...:
        ...
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from ai_copilot_infra.core.config import Settings, get_settings
from ai_copilot_infra.core.llm_service import LLMService
from ai_copilot_infra.core.mcp_client import MCPClient
from ai_copilot_infra.core.redis_service import RedisService
from ai_copilot_infra.workflows.copilot_workflow import CopilotWorkflow

# ── Settings ──────────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]


# ── LLMService ────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    """Singleton LLMService — one AsyncOpenAI client for the process lifetime."""
    return LLMService()


LLMServiceDep = Annotated[LLMService, Depends(get_llm_service)]


# ── RedisService ──────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_redis_service() -> RedisService:
    """Singleton RedisService — borrows from the shared connection pool."""
    return RedisService()


RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]


# ── MCPClient ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_mcp_client() -> MCPClient:
    """Singleton MCPClient — reuses a single base URL for the process lifetime."""
    return MCPClient()


MCPClientDep = Annotated[MCPClient, Depends(get_mcp_client)]


# ── CopilotWorkflow ───────────────────────────────────────────────────────────


def get_copilot_workflow(
    llm: LLMServiceDep,
    redis: RedisServiceDep,
    mcp: MCPClientDep,
) -> CopilotWorkflow:
    """
    CopilotWorkflow assembled from injected singletons.

    Not cached — the workflow is stateless and its dependencies are
    already singletons, so construction per request is O(1).
    """
    return CopilotWorkflow(
        llm_service=llm,
        redis=redis,
        mcp=mcp,
    )


WorkflowDep = Annotated[CopilotWorkflow, Depends(get_copilot_workflow)]
