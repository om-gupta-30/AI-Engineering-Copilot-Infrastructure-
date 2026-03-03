"""
Application entrypoint.
Run with: uvicorn ai_copilot_infra.main:app --reload
"""

from ai_copilot_infra.api.app import app  # noqa: F401 — re-exported for uvicorn

__all__ = ["app"]
