"""
MCP Server — standalone FastAPI application exposing tool execution over HTTP.

Endpoints:
  POST /execute-tool   — validate, execute, and return tool results
  GET  /tools          — list all registered tools with their schemas
  GET  /health         — liveness probe

Startup:
  Registers LibraryDetectionTool and DocumentationFetchTool into a
  dedicated ToolRegistry instance (separate from the main API's default_registry).

Run standalone:
  uvicorn ai_copilot_infra.mcp_server.app:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from ai_copilot_infra.mcp_server.documentation_fetch_tool import DocumentationFetchTool
from ai_copilot_infra.mcp_server.library_detection_tool import LibraryDetectionTool
from ai_copilot_infra.mcp_server.registry import ToolNotFoundError, ToolRegistry
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)

# ── Registry scoped to this server ────────────────────────────────────────────

_registry = ToolRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Register tools on startup."""
    _registry.register_tool(LibraryDetectionTool(), overwrite=True)
    _registry.register_tool(DocumentationFetchTool(), overwrite=True)
    logger.info(
        "mcp_server_started",
        registered_tools=_registry.tool_names(),
    )
    yield
    logger.info("mcp_server_shutdown")


app = FastAPI(
    title="MCP Tool Server",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Request / response models ─────────────────────────────────────────────────


class ExecuteToolRequest(BaseModel):
    tool_name: str = Field(
        ...,
        min_length=1,
        description="Registered tool identifier (e.g. 'detect_libraries').",
        examples=["detect_libraries", "fetch_documentation"],
    )
    input: dict[str, Any] = Field(
        ...,
        description="Tool-specific input arguments. Validated against the tool's InputSchema.",
        examples=[{"user_query": "How do I use FastAPI with Redis?"}],
    )


class ExecuteToolResponse(BaseModel):
    tool_name: str
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    execution_time_ms: float


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.post(
    "/execute-tool",
    response_model=ExecuteToolResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute a registered MCP tool",
    responses={
        404: {"description": "Tool not found in the registry"},
        422: {"description": "Input validation failed against the tool's schema"},
        500: {"description": "Tool execution failed"},
    },
)
async def execute_tool(body: ExecuteToolRequest) -> ExecuteToolResponse:
    """
    Validate inputs, execute the named tool, and return structured output.
    """
    start = time.perf_counter()

    logger.info(
        "tool_request_received",
        tool_name=body.tool_name,
        input_keys=list(body.input.keys()),
    )

    # ── Resolve tool ──────────────────────────────────────────────────────────
    try:
        tool = _registry.get_tool(body.tool_name)
    except ToolNotFoundError as err:
        logger.warning(
            "tool_not_found",
            tool_name=body.tool_name,
            available=_registry.tool_names(),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{body.tool_name}' not found. Available: {_registry.tool_names()}",
        ) from err

    # ── Validate input against the tool's schema ──────────────────────────────
    try:
        tool.InputSchema.model_validate(body.input)
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        logger.warning(
            "tool_input_validation_failed",
            tool_name=body.tool_name,
            error=str(exc),
            execution_time_ms=elapsed_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Input validation failed: {exc}",
        ) from exc

    # ── Execute ───────────────────────────────────────────────────────────────
    result = await tool.run(body.input)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

    if not result.success:
        logger.error(
            "tool_execution_failed",
            tool_name=body.tool_name,
            error=result.error,
            execution_time_ms=elapsed_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Tool execution failed.",
        )

    output_dict = result.data.model_dump() if result.data else None

    logger.info(
        "tool_request_complete",
        tool_name=body.tool_name,
        success=True,
        execution_time_ms=elapsed_ms,
    )

    return ExecuteToolResponse(
        tool_name=body.tool_name,
        success=True,
        output=output_dict,
        execution_time_ms=elapsed_ms,
    )


@app.get("/tools", summary="List all registered tools with schemas")
async def list_tools() -> list[dict[str, Any]]:
    """Return MCP-compatible tool descriptors for all registered tools."""
    return _registry.list_tools()


@app.get("/health", summary="MCP server liveness probe")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "mcp_tool_server",
        "tools_registered": str(len(_registry)),
    }
