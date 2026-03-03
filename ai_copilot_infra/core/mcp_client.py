"""
MCPClient — async HTTP client that calls the MCP Tool Server over the network.

Replaces direct ToolRegistry usage. The workflow layer now sends tool
execution requests over HTTP to the MCP server (POST /execute-tool),
making the tool server independently deployable and scalable.

Configuration (via environment / .env):
  MCP_BASE_URL          — base URL of the MCP server (e.g. http://mcp:8100)
  MCP_TIMEOUT_SECONDS   — per-request timeout, default 30 s
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ai_copilot_infra.core.config import settings
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


# ── Domain exceptions ─────────────────────────────────────────────────────────


class MCPClientError(Exception):
    """Base exception for all MCPClient errors."""


class MCPConnectionError(MCPClientError):
    """Raised when the MCP server is unreachable."""


class MCPTimeoutError(MCPClientError):
    """Raised when the request exceeds the configured timeout."""


class MCPToolNotFoundError(MCPClientError):
    """Raised when the MCP server returns 404 for a tool name."""


class MCPValidationError(MCPClientError):
    """Raised when the MCP server returns 422 for invalid input."""


class MCPExecutionError(MCPClientError):
    """Raised when the MCP server returns 500 (tool execution failed)."""


# ── Client ────────────────────────────────────────────────────────────────────


class MCPClient:
    """
    Async HTTP client for the MCP Tool Server.

    Sends tool execution requests to POST {base_url}/execute-tool and
    returns the parsed output dict. All HTTP, timeout, and error-status
    edge cases are handled and surfaced as typed exceptions.

    Usage:
        client = MCPClient()
        result = await client.execute_tool("detect_libraries", {"user_query": "..."})
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.mcp_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.mcp_timeout_seconds

    async def execute_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        trace_id: str = "",
    ) -> dict[str, Any]:
        """
        Execute a tool on the remote MCP server.

        Args:
            tool_name:  Registered tool identifier (e.g. "detect_libraries").
            input_data: Tool-specific input arguments.
            trace_id:   Opaque request trace identifier forwarded to all log lines.

        Returns:
            The tool's output dict (contents of the "output" field in the response).

        Raises:
            MCPToolNotFoundError  — 404: tool not registered
            MCPValidationError    — 422: input failed schema validation
            MCPExecutionError     — 500: tool execution failed
            MCPTimeoutError       — request exceeded timeout
            MCPConnectionError    — network-level failure
        """
        url = f"{self._base_url}/execute-tool"
        payload = {"tool_name": tool_name, "input": input_data}

        logger.info(
            "mcp_call_start",
            trace_id=trace_id,
            step=f"mcp_{tool_name}",
            tool_name=tool_name,
            url=url,
            input_keys=list(input_data.keys()),
        )

        start = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.error(
                "mcp_call_timeout",
                trace_id=trace_id,
                step=f"mcp_{tool_name}",
                tool_name=tool_name,
                timeout_seconds=self._timeout,
                latency_ms=latency_ms,
            )
            raise MCPTimeoutError(
                f"MCP server timed out after {self._timeout}s for tool '{tool_name}'."
            ) from exc
        except httpx.RequestError as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.error(
                "mcp_call_connection_error",
                trace_id=trace_id,
                step=f"mcp_{tool_name}",
                tool_name=tool_name,
                error=str(exc),
                latency_ms=latency_ms,
            )
            raise MCPConnectionError(
                f"Failed to connect to MCP server at {self._base_url}: {exc}"
            ) from exc

        latency_ms = round((time.perf_counter() - start) * 1000, 3)

        # ── Handle non-200 responses ──────────────────────────────────────────
        if response.status_code == 404:
            detail = self._extract_detail(response)
            logger.warning(
                "mcp_tool_not_found",
                trace_id=trace_id,
                step=f"mcp_{tool_name}",
                tool_name=tool_name,
                detail=detail,
                latency_ms=latency_ms,
            )
            raise MCPToolNotFoundError(f"Tool '{tool_name}' not found on MCP server: {detail}")

        if response.status_code == 422:
            detail = self._extract_detail(response)
            logger.warning(
                "mcp_input_validation_failed",
                trace_id=trace_id,
                step=f"mcp_{tool_name}",
                tool_name=tool_name,
                detail=detail,
                latency_ms=latency_ms,
            )
            raise MCPValidationError(f"Input validation failed for '{tool_name}': {detail}")

        if response.status_code >= 400:
            detail = self._extract_detail(response)
            logger.error(
                "mcp_execution_error",
                trace_id=trace_id,
                step=f"mcp_{tool_name}",
                tool_name=tool_name,
                status_code=response.status_code,
                detail=detail,
                latency_ms=latency_ms,
            )
            raise MCPExecutionError(
                f"MCP server returned {response.status_code} for '{tool_name}': {detail}"
            )

        # ── Parse successful response ─────────────────────────────────────────
        body = response.json()
        output = body.get("output")

        logger.info(
            "mcp_call_complete",
            trace_id=trace_id,
            step=f"mcp_{tool_name}",
            tool_name=tool_name,
            success=body.get("success", True),
            execution_time_ms=body.get("execution_time_ms"),
            latency_ms=latency_ms,
        )

        return output or {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        """Pull the 'detail' field from a FastAPI error response body."""
        try:
            return str(response.json().get("detail", response.text[:200]))
        except Exception:
            return response.text[:200]
