"""
Copilot API routes.

Endpoints:
  POST /copilot/query — submit a natural language engineering query

Rate limiting:
  20 requests per minute per client IP, enforced via Redis INCR + EXPIRE.
  Exceeding the limit returns HTTP 429.

Observability:
  A UUID trace_id is generated at the start of every request and threaded
  through the workflow, all MCP calls, and every log line so the full
  request lifecycle can be correlated without an external tracing backend.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ai_copilot_infra.core.dependencies import RedisServiceDep, WorkflowDep
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/copilot", tags=["copilot"])

# ── Rate-limit config ─────────────────────────────────────────────────────────

_RATE_LIMIT_MAX = 20  # requests allowed per window
_RATE_LIMIT_TTL = 60  # window size in seconds


# ── Request / response models ─────────────────────────────────────────────────


class CopilotQueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language engineering question.",
        examples=["How do I configure Celery with Redis in Docker Compose?"],
    )


class CopilotQueryResponse(BaseModel):
    answer: str | None
    libraries_used: list[str]
    validation_passed: bool
    cached: bool = False
    trace_id: str = ""


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post(
    "/query",
    response_model=CopilotQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit an engineering query to the AI copilot",
    responses={
        429: {"description": "Rate limit exceeded — max 20 requests per minute per IP"},
        500: {"description": "Internal server error"},
    },
)
async def copilot_query(
    request: Request,
    body: CopilotQueryRequest,
    workflow: WorkflowDep,
    redis: RedisServiceDep,
) -> CopilotQueryResponse:
    """
    Run the full copilot pipeline for the given query.

    - Checks Redis cache first; returns instantly on a hit.
    - Detects referenced libraries, fetches their documentation,
      constructs a grounded prompt, calls the LLM, and validates output.
    - Caches successful responses for 1 hour.
    - Every log line carries trace_id for end-to-end request correlation.
    """
    trace_id = str(uuid.uuid4())
    start = time.perf_counter()
    client_ip = _get_client_ip(request)

    logger.info(
        "copilot_request_received",
        trace_id=trace_id,
        step="api_ingress",
        client_ip=client_ip,
        query_length=len(body.query),
        query_preview=body.query[:80],
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_key = f"rate:{client_ip}:copilot"
    request_count = await redis.increment(rate_key, ttl=_RATE_LIMIT_TTL)

    if request_count > _RATE_LIMIT_MAX:
        logger.warning(
            "copilot_rate_limit_exceeded",
            trace_id=trace_id,
            step="rate_limit",
            client_ip=client_ip,
            request_count=request_count,
            limit=_RATE_LIMIT_MAX,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum {_RATE_LIMIT_MAX} requests per minute.",
        )

    # ── Workflow ──────────────────────────────────────────────────────────────
    try:
        result = await workflow.run(body.query, trace_id=trace_id)
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        logger.error(
            "copilot_internal_error",
            trace_id=trace_id,
            step="workflow",
            client_ip=client_ip,
            error=str(exc),
            latency_ms=elapsed_ms,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing your request.",
        ) from exc

    # ── Response ──────────────────────────────────────────────────────────────
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    logger.info(
        "copilot_request_complete",
        trace_id=trace_id,
        step="api_egress",
        client_ip=client_ip,
        cached=result.get("cached", False),
        validation_passed=result.get("validation_passed", False),
        libraries_used=result.get("libraries_used", []),
        latency_ms=elapsed_ms,
    )

    if result.get("error"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["error"],
        )

    return CopilotQueryResponse(
        answer=result["answer"],
        libraries_used=result["libraries_used"],
        validation_passed=result["validation_passed"],
        cached=result.get("cached", False),
        trace_id=result.get("trace_id", trace_id),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_client_ip(request: Request) -> str:
    """
    Resolve the real client IP, respecting X-Forwarded-For when behind a proxy.
    Falls back to the direct connection address.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
