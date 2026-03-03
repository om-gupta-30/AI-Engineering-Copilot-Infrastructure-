"""
context — Context7 integration and session management.

Public surface:
  Context7Client          — async HTTP client for /docs/{library} endpoint
  Context7Error           — base exception
  Context7ConfigError     — CONTEXT7_BASE_URL not set
  Context7TimeoutError    — request timed out
  Context7HTTPError       — non-2xx response (carries .status_code)
  Context7EmptyResponseError — 200 but no documentation content
"""

from ai_copilot_infra.context.context7_client import (
    Context7Client,
    Context7ConfigError,
    Context7EmptyResponseError,
    Context7Error,
    Context7HTTPError,
    Context7TimeoutError,
)

__all__ = [
    "Context7Client",
    "Context7Error",
    "Context7ConfigError",
    "Context7TimeoutError",
    "Context7HTTPError",
    "Context7EmptyResponseError",
]
