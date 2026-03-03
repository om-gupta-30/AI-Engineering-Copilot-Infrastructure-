"""
ToolRegistry — central catalogue of all registered MCP tools.

Responsibilities:
  - Accept tool registrations at startup (or dynamically)
  - Resolve tool instances by name for the client layer
  - Expose tool descriptors for protocol advertisement

Usage:
    registry = ToolRegistry()
    registry.register_tool(LibraryDetectionTool())
    registry.register_tool(DocumentationFetchTool())

    tool = registry.get_tool("detect_libraries")
    result = await tool.run({"user_query": "How do I use FastAPI with Redis?"})
"""

from typing import Any

from ai_copilot_infra.mcp_server.base import BaseTool, ToolResult
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


class ToolNotFoundError(KeyError):
    """Raised when a requested tool name has no registration."""


class DuplicateToolError(ValueError):
    """Raised when a tool with the same name is registered twice."""


class ToolRegistry:
    """
    Thread-safe (at the asyncio level) registry of BaseTool instances.
    Instantiate once and share across the application lifetime.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}  # type: ignore[type-arg]

    # ── Registration ──────────────────────────────────────────────────────────

    def register_tool(self, tool: BaseTool, *, overwrite: bool = False) -> None:  # type: ignore[type-arg]
        """
        Add a tool to the registry.

        Args:
            tool:      Instantiated BaseTool subclass.
            overwrite: If True, silently replaces an existing registration.
                       If False (default), raises DuplicateToolError.

        Raises:
            DuplicateToolError: When name collision occurs and overwrite=False.
        """
        if tool.name in self._tools and not overwrite:
            raise DuplicateToolError(
                f"Tool '{tool.name}' is already registered. " "Pass overwrite=True to replace it."
            )

        self._tools[tool.name] = tool
        logger.info("tool_registered", tool=tool.name)

    def unregister_tool(self, name: str) -> None:
        """Remove a tool from the registry by name."""
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' is not registered.")
        del self._tools[name]
        logger.info("tool_unregistered", tool=name)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get_tool(self, name: str) -> BaseTool:  # type: ignore[type-arg]
        """
        Retrieve a tool instance by name.

        Raises:
            ToolNotFoundError: When the name has no registration.
        """
        try:
            return self._tools[name]
        except KeyError:
            available = list(self._tools.keys())
            raise ToolNotFoundError(
                f"Tool '{name}' not found. Available tools: {available}"
            ) from None

    def has_tool(self, name: str) -> bool:
        """Return True if a tool with this name is registered."""
        return name in self._tools

    # ── Introspection ─────────────────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, Any]]:
        """
        Return MCP-compatible tool descriptors for all registered tools.
        Suitable for advertising the toolset to a connected LLM / client.
        """
        return [tool.as_tool_definition() for tool in self._tools.values()]

    def tool_names(self) -> list[str]:
        """Return a sorted list of registered tool names."""
        return sorted(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={self.tool_names()})"

    # ── Execution shortcut ────────────────────────────────────────────────────

    async def call(self, tool_name: str, raw_inputs: dict[str, Any]) -> ToolResult:  # type: ignore[type-arg]
        """
        Convenience method: resolve a tool by name and execute it.

        Args:
            tool_name:  Registered tool identifier.
            raw_inputs: Unvalidated argument dict (validation happens inside BaseTool.run).

        Returns:
            ToolResult envelope.

        Raises:
            ToolNotFoundError: When tool_name is not registered.
        """
        tool = self.get_tool(tool_name)
        return await tool.run(raw_inputs)


# ── Module-level default registry ─────────────────────────────────────────────
# Import this singleton from anywhere; populate it in api/app.py lifespan.

default_registry: ToolRegistry = ToolRegistry()
