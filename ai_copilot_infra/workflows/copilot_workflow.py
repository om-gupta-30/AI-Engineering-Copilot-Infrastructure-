"""
CopilotWorkflow — deterministic 6-step AI engineering copilot pipeline.

Execution order (never skipped, never reordered):

  Step 1  IntentClassificationStep   — label the query intent
  Step 2  LibraryDetectionStep       — detect referenced libraries via MCP server
  Step 3  DocumentationFetchStep     — retrieve docs per library via MCP server
  Step 4  PromptConstructionStep     — build the grounded LLM prompt
  Step 5  LLMGenerationStep          — call LLMService (real OpenAI call)
  Step 6  PostValidationStep         — validate response quality

Every log line includes {"trace_id": "...", "step": "..."} for end-to-end
request correlation without an external tracing backend.

Entry point:
    workflow = CopilotWorkflow(
        llm_service=LLMService(),
        redis=RedisService(),
        mcp=MCPClient(),
    )
    result = await workflow.run("How do I use FastAPI with Redis?", trace_id="abc-123")
"""

from __future__ import annotations

import json
import time

from ai_copilot_infra.core.llm_service import LLMService, LLMServiceError
from ai_copilot_infra.core.mcp_client import MCPClient, MCPClientError
from ai_copilot_infra.core.redis_service import RedisService
from ai_copilot_infra.core.validation import OutputValidator
from ai_copilot_infra.observability.logger import get_logger
from ai_copilot_infra.workflows.base import StepPipeline, WorkflowStep
from ai_copilot_infra.workflows.state import WorkflowState

logger = get_logger(__name__)


# ── Step 1: Intent Classification ─────────────────────────────────────────────


class IntentClassificationStep(WorkflowStep):
    """Classify the high-level intent of the user query."""

    name = "intent_classification"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        state.intent = "documentation_query"
        logger.debug(
            "intent_classified",
            trace_id=state.trace_id,
            step=self.name,
            intent=state.intent,
            query=state.user_query[:80],
        )
        return state


# ── Step 2: Library Detection ─────────────────────────────────────────────────


class LibraryDetectionStep(WorkflowStep):
    """Call the MCP server's detect_libraries tool via HTTP."""

    name = "library_detection"

    def __init__(self, mcp: MCPClient) -> None:
        self._mcp = mcp

    async def execute(self, state: WorkflowState) -> WorkflowState:
        start = time.perf_counter()
        try:
            output = await self._mcp.execute_tool(
                "detect_libraries",
                {"user_query": state.user_query},
                trace_id=state.trace_id,
            )
        except MCPClientError as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.warning(
                "library_detection_failed",
                trace_id=state.trace_id,
                step=self.name,
                error=str(exc),
                error_type=type(exc).__name__,
                latency_ms=latency_ms,
                query=state.user_query[:80],
            )
            state.detected_libraries = []
            return state

        latency_ms = round((time.perf_counter() - start) * 1000, 3)
        detected = output.get("detected", [])
        state.detected_libraries = [lib["name"] for lib in detected if isinstance(lib, dict)]

        logger.info(
            "libraries_detected",
            trace_id=state.trace_id,
            step=self.name,
            libraries=state.detected_libraries,
            total=output.get("total_detected", len(state.detected_libraries)),
            latency_ms=latency_ms,
        )
        return state


# ── Step 3: Documentation Fetch ───────────────────────────────────────────────


class DocumentationFetchStep(WorkflowStep):
    """For each detected library, fetch docs from the MCP server."""

    name = "documentation_fetch"

    def __init__(self, mcp: MCPClient) -> None:
        self._mcp = mcp

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if not state.detected_libraries:
            logger.debug(
                "documentation_fetch_skipped",
                trace_id=state.trace_id,
                step=self.name,
                reason="no_detected_libraries",
            )
            return state

        for library_name in state.detected_libraries:
            start = time.perf_counter()
            try:
                output = await self._mcp.execute_tool(
                    "fetch_documentation",
                    {"library_name": library_name},
                    trace_id=state.trace_id,
                )
            except MCPClientError as exc:
                latency_ms = round((time.perf_counter() - start) * 1000, 3)
                logger.warning(
                    "documentation_fetch_failed",
                    trace_id=state.trace_id,
                    step=self.name,
                    library=library_name,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    latency_ms=latency_ms,
                )
                continue

            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            doc_text = self._flatten_sections(output.get("sections", []))
            state.retrieved_docs[library_name] = doc_text

            logger.info(
                "documentation_fetched",
                trace_id=state.trace_id,
                step=self.name,
                library=library_name,
                sections=len(output.get("sections", [])),
                chars=len(doc_text),
                latency_ms=latency_ms,
            )

        return state

    @staticmethod
    def _flatten_sections(sections: list[dict]) -> str:
        parts: list[str] = []
        for section in sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            parts.append(f"**{heading}**\n{content}")
        return "\n\n".join(parts)


# ── Step 4: Prompt Construction ───────────────────────────────────────────────

_PROMPT_TEMPLATE = """\
You are an internal AI engineering copilot.

Use ONLY the documentation provided below.

USER QUESTION:
{user_query}

DOCUMENTATION:
{docs_block}

Provide accurate, production-safe answer.
This is grounding.\
"""


class PromptConstructionStep(WorkflowStep):
    """Build the grounded LLM prompt from query + retrieved docs."""

    name = "prompt_construction"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        state.constructed_prompt = _PROMPT_TEMPLATE.format(
            user_query=state.user_query,
            docs_block=state.docs_as_text(),
        )

        logger.debug(
            "prompt_constructed",
            trace_id=state.trace_id,
            step=self.name,
            prompt_length=len(state.constructed_prompt),
            libraries_in_context=list(state.retrieved_docs.keys()),
        )
        return state


# ── Step 5: LLM Generation ────────────────────────────────────────────────────


class LLMGenerationStep(WorkflowStep):
    """Send the grounded prompt to LLMService and store the response."""

    name = "llm_generation"

    def __init__(self, llm_service: LLMService) -> None:
        self._llm = llm_service

    async def execute(self, state: WorkflowState) -> WorkflowState:
        result = await self._llm.generate(state.constructed_prompt or "")

        state.llm_output = result["content"]

        logger.info(
            "llm_generation_complete",
            trace_id=state.trace_id,
            step=self.name,
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            latency_ms=result["latency_ms"],
            output_length=len(state.llm_output),
        )
        return state


# ── Step 6: Post-Validation ───────────────────────────────────────────────────


class PostValidationStep(WorkflowStep):
    """Run the OutputValidator battery against the LLM response."""

    name = "post_validation"

    def __init__(self) -> None:
        self._validator = OutputValidator()

    async def execute(self, state: WorkflowState) -> WorkflowState:
        start = time.perf_counter()
        verdict = self._validator.validate(
            generated_text=state.llm_output or "",
            detected_libraries=state.detected_libraries,
            retrieved_docs=state.retrieved_docs,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 3)

        state.validation_passed = verdict["passed"]
        state.validation_reasons = verdict["reasons"]

        logger.info(
            "post_validation_complete",
            trace_id=state.trace_id,
            step=self.name,
            passed=state.validation_passed,
            reasons=state.validation_reasons,
            latency_ms=latency_ms,
        )
        return state


# ── CopilotWorkflow ───────────────────────────────────────────────────────────


class CopilotWorkflow:
    """
    Orchestrates the full copilot pipeline for a single user query.

    All tool calls go through MCPClient (HTTP to MCP server).
    Every log line carries trace_id and step for end-to-end observability.

    Usage:
        workflow = CopilotWorkflow(
            llm_service=LLMService(),
            redis=RedisService(),
            mcp=MCPClient(),
        )
        result = await workflow.run("How do I use FastAPI with Redis?", trace_id="abc-123")
    """

    _CACHE_TTL = 3600

    def __init__(
        self,
        llm_service: LLMService,
        redis: RedisService,
        mcp: MCPClient,
    ) -> None:
        self._llm_service = llm_service
        self._redis = redis
        self._mcp = mcp
        self._pipeline = StepPipeline(
            steps=[
                IntentClassificationStep(),
                LibraryDetectionStep(mcp=mcp),
                DocumentationFetchStep(mcp=mcp),
                PromptConstructionStep(),
                LLMGenerationStep(llm_service=llm_service),
                PostValidationStep(),
            ]
        )

    async def run(self, user_query: str, trace_id: str = "") -> dict:
        """
        Execute the full 6-step pipeline for the given query.

        Args:
            user_query: Raw natural language input from the user.
            trace_id:   Request-scoped trace identifier generated by the API layer.
                        A UUID is generated internally when not supplied.

        Cache behaviour:
          - Before Step 2, the query is checked against Redis.
          - After a validated pipeline run, the response is cached for 1 hour.
          - Failed (validation) and error responses are never cached.
        """
        start = time.perf_counter()
        cache_key = f"copilot:{hash(user_query)}"

        # Seed WorkflowState with the caller-supplied trace_id so every step
        # and every MCP call can log it without extra plumbing.
        effective_trace_id = trace_id or state_trace_id()
        state = WorkflowState(user_query=user_query, trace_id=effective_trace_id)

        logger.info(
            "workflow_start",
            trace_id=state.trace_id,
            step="workflow",
            query=user_query[:80],
            cache_key=cache_key,
        )

        # ── Cache check ───────────────────────────────────────────────────────
        cached_value = await self._redis.get(cache_key)
        if cached_value is not None:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.info(
                "workflow_cache_hit",
                trace_id=state.trace_id,
                step="workflow",
                cache_key=cache_key,
                latency_ms=elapsed_ms,
            )
            response: dict = json.loads(cached_value)
            response["cached"] = True
            response["trace_id"] = state.trace_id
            return response

        logger.info(
            "workflow_cache_miss",
            trace_id=state.trace_id,
            step="workflow",
            cache_key=cache_key,
        )

        # ── Pipeline execution (Steps 1–6) ────────────────────────────────────
        try:
            state = await self._pipeline.run(state)
        except LLMServiceError as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.error(
                "workflow_llm_failure",
                trace_id=state.trace_id,
                step="llm_generation",
                error=str(exc),
                error_type=type(exc).__name__,
                libraries_detected=state.detected_libraries,
                latency_ms=elapsed_ms,
            )
            return {
                "answer": None,
                "libraries_used": state.detected_libraries,
                "validation_passed": False,
                "validation_reasons": [f"LLM failure: {exc}"],
                "error": str(exc),
                "cached": False,
                "trace_id": state.trace_id,
            }

        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

        # ── Validation guardrail ──────────────────────────────────────────────
        if not state.validation_passed:
            logger.warning(
                "workflow_validation_failed",
                trace_id=state.trace_id,
                step="post_validation",
                reasons=state.validation_reasons,
                libraries_detected=state.detected_libraries,
                output_length=len(state.llm_output or ""),
                latency_ms=elapsed_ms,
            )
            return {
                "answer": "Response failed validation. Please retry.",
                "libraries_used": state.detected_libraries,
                "validation_passed": False,
                "validation_reasons": state.validation_reasons,
                "error": None,
                "cached": False,
                "trace_id": state.trace_id,
            }

        result = {
            "answer": state.llm_output,
            "libraries_used": state.detected_libraries,
            "validation_passed": True,
            "validation_reasons": state.validation_reasons,
            "error": None,
            "cached": False,
            "trace_id": state.trace_id,
        }

        # ── Cache write (only on validated responses) ─────────────────────────
        await self._redis.set(cache_key, json.dumps(result), ttl=self._CACHE_TTL)
        logger.info(
            "workflow_response_cached",
            trace_id=state.trace_id,
            step="workflow",
            cache_key=cache_key,
            ttl_seconds=self._CACHE_TTL,
        )

        logger.info(
            "workflow_complete",
            trace_id=state.trace_id,
            step="workflow",
            libraries_used=state.detected_libraries,
            validation_passed=True,
            latency_ms=elapsed_ms,
        )

        return result


# ── Internal helper ───────────────────────────────────────────────────────────


def state_trace_id() -> str:
    """Generate a fresh UUID trace_id (fallback when caller omits it)."""
    import uuid

    return str(uuid.uuid4())
