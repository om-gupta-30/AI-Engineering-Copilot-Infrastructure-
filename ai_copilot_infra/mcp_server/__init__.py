"""
mcp_server — Model Context Protocol tool system.

Public surface:
  BaseTool          — abstract base for all tools
  ToolResult        — execution envelope (success, data, error, duration_ms)
  ToolRegistry      — register / get / list tools
  default_registry  — module-level singleton registry
  setup_default_tools — populate default_registry with built-in tools
"""

from ai_copilot_infra.mcp_server.base import BaseTool, ToolResult
from ai_copilot_infra.mcp_server.registry import ToolRegistry, default_registry
from ai_copilot_infra.mcp_server.tools import setup_default_tools

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "default_registry",
    "setup_default_tools",
]
