"""
tools.py — wires concrete tool implementations into the default registry.

Import and call `setup_default_tools()` once during application startup
(e.g. inside the FastAPI lifespan) to populate the shared registry.

Adding a new tool:
  1. Implement a BaseTool subclass in its own module.
  2. Import it here and register it in setup_default_tools().
"""

from ai_copilot_infra.mcp_server.documentation_fetch_tool import DocumentationFetchTool
from ai_copilot_infra.mcp_server.library_detection_tool import LibraryDetectionTool
from ai_copilot_infra.mcp_server.registry import ToolRegistry, default_registry
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


def setup_default_tools(registry: ToolRegistry = default_registry) -> None:
    """
    Register all production tools into the given registry.
    Idempotent if called more than once (overwrite=True).
    """
    tools = [
        LibraryDetectionTool(),
        DocumentationFetchTool(),
    ]

    for tool in tools:
        registry.register_tool(tool, overwrite=True)

    logger.info(
        "mcp_tools_loaded",
        count=len(tools),
        names=registry.tool_names(),
    )


__all__ = [
    "setup_default_tools",
    "LibraryDetectionTool",
    "DocumentationFetchTool",
]
