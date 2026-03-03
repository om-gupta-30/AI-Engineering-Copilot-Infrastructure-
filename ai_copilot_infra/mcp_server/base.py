"""
BaseTool — abstract foundation for all MCP-style tools.

Every tool in the system inherits from BaseTool and declares:
  - name          : unique snake_case identifier
  - description   : human-readable description surfaced to the LLM
  - InputSchema   : Pydantic model that validates incoming arguments
  - OutputSchema  : Pydantic model that structures the result
  - execute()     : async implementation of the tool's logic

The protocol layer (ToolRegistry, MCPClient) deals only with this
interface, keeping individual tools fully decoupled from transport.
"""

import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)

# Generic type vars so execute() is fully typed end-to-end
InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


# ── Envelope models ──────────────────────────────────────────────────────────


class ToolResult(BaseModel, Generic[OutputT]):
    """Wrapper returned by every tool call."""

    tool_name: str
    success: bool
    data: OutputT | None = None
    error: str | None = None
    duration_ms: float


class ToolError(BaseModel):
    """Structured error payload embedded in ToolResult when success=False."""

    code: str
    message: str
    detail: str | None = None


# ── Base class ────────────────────────────────────────────────────────────────


class BaseTool(ABC, Generic[InputT, OutputT]):
    """
    Abstract base for all MCP tools.

    Subclasses must define:
      - name            (ClassVar[str])
      - description     (ClassVar[str])
      - InputSchema     (ClassVar[type[BaseModel]])
      - OutputSchema    (ClassVar[type[BaseModel]])
      - execute(inputs) async method
    """

    name: ClassVar[str]
    description: ClassVar[str]
    InputSchema: ClassVar[type[BaseModel]]
    OutputSchema: ClassVar[type[BaseModel]]

    # ── Protocol-facing descriptor ────────────────────────────────────────────

    def as_tool_definition(self) -> dict[str, Any]:
        """
        Emit an MCP-compatible tool descriptor (JSON Schema for input).
        Used by the registry to advertise available tools.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.InputSchema.model_json_schema(),
            "outputSchema": self.OutputSchema.model_json_schema(),
        }

    # ── Execution lifecycle ───────────────────────────────────────────────────

    @abstractmethod
    async def execute(self, inputs: InputT) -> OutputT:
        """
        Core tool logic. Receives a validated InputSchema instance.
        Must return an OutputSchema instance.
        """
        ...

    async def run(self, raw_inputs: dict[str, Any]) -> ToolResult:  # type: ignore[type-arg]
        """
        Public entry point called by the registry / client.

        1. Validates raw_inputs against InputSchema
        2. Calls execute()
        3. Returns a ToolResult envelope with timing and error handling
        """
        start = time.perf_counter()
        logger.info(
            "tool_execution_start",
            tool=self.name,
            inputs=raw_inputs,
        )

        try:
            validated: InputT = self.InputSchema.model_validate(raw_inputs)  # type: ignore[assignment]
            output: OutputT = await self.execute(validated)
            duration_ms = round((time.perf_counter() - start) * 1000, 3)

            logger.info(
                "tool_execution_end",
                tool=self.name,
                success=True,
                duration_ms=duration_ms,
            )

            return ToolResult(
                tool_name=self.name,
                success=True,
                data=output,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.error(
                "tool_execution_error",
                tool=self.name,
                error=str(exc),
                exc_info=True,
                duration_ms=duration_ms,
            )
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
