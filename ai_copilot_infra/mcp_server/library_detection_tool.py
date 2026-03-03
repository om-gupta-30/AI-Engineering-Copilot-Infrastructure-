"""
LibraryDetectionTool — detects engineering libraries mentioned in a user query.

Uses a curated keyword map: each library entry holds a set of case-insensitive
trigger terms. When any trigger appears in the query the library is included in
the result.

No LLM involved — this is a pure protocol / pattern-matching layer.
"""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, Field

from ai_copilot_infra.mcp_server.base import BaseTool

# ── Schema definitions ────────────────────────────────────────────────────────


class LibraryDetectionInput(BaseModel):
    """Input schema for LibraryDetectionTool."""

    user_query: str = Field(
        ...,
        min_length=1,
        description="Natural language query that may reference one or more libraries.",
        examples=["How do I use FastAPI with Redis caching?"],
    )


class DetectedLibrary(BaseModel):
    """A single detected library with metadata."""

    name: str = Field(..., description="Canonical library name.")
    category: str = Field(..., description="Ecosystem category (e.g. 'web', 'cache', 'queue').")
    matched_keywords: list[str] = Field(
        default_factory=list,
        description="Which keywords triggered this detection.",
    )
    docs_url: str = Field(..., description="Official documentation URL.")


class LibraryDetectionOutput(BaseModel):
    """Output schema for LibraryDetectionTool."""

    query: str = Field(..., description="The original user query.")
    detected: list[DetectedLibrary] = Field(
        default_factory=list,
        description="Libraries detected in the query.",
    )
    total_detected: int = Field(..., description="Count of detected libraries.")


# ── Keyword catalogue ─────────────────────────────────────────────────────────

# Structure: library_name -> {canonical_name, category, docs_url, triggers}
# Triggers are lowercase; matching is case-insensitive whole-word / substring.

_LIBRARY_CATALOGUE: list[dict] = [
    {
        "name": "FastAPI",
        "category": "web",
        "docs_url": "https://fastapi.tiangolo.com",
        "triggers": {"fastapi", "fast api", "fast-api"},
    },
    {
        "name": "Redis",
        "category": "cache",
        "docs_url": "https://redis.io/docs",
        "triggers": {"redis", "redis-py", "aioredis", "redis.asyncio"},
    },
    {
        "name": "Celery",
        "category": "queue",
        "docs_url": "https://docs.celeryq.dev",
        "triggers": {"celery", "celerybeat", "celery beat", "celery worker"},
    },
    {
        "name": "Docker",
        "category": "infra",
        "docs_url": "https://docs.docker.com",
        "triggers": {"docker", "dockerfile", "docker-compose", "docker compose", "container"},
    },
    {
        "name": "Pydantic",
        "category": "validation",
        "docs_url": "https://docs.pydantic.dev",
        "triggers": {"pydantic", "basemodel", "model_validator", "field_validator"},
    },
    {
        "name": "SQLAlchemy",
        "category": "orm",
        "docs_url": "https://docs.sqlalchemy.org",
        "triggers": {"sqlalchemy", "sql alchemy", "orm", "alembic"},
    },
    {
        "name": "Langchain",
        "category": "llm",
        "docs_url": "https://python.langchain.com/docs",
        "triggers": {"langchain", "lang chain", "langchain-core"},
    },
    {
        "name": "Langfuse",
        "category": "observability",
        "docs_url": "https://langfuse.com/docs",
        "triggers": {"langfuse", "lang fuse"},
    },
    {
        "name": "Loguru",
        "category": "logging",
        "docs_url": "https://loguru.readthedocs.io",
        "triggers": {"loguru"},
    },
    {
        "name": "Pytest",
        "category": "testing",
        "docs_url": "https://docs.pytest.org",
        "triggers": {"pytest", "pytest-asyncio", "conftest"},
    },
    {
        "name": "Uvicorn",
        "category": "server",
        "docs_url": "https://www.uvicorn.org",
        "triggers": {"uvicorn"},
    },
    {
        "name": "httpx",
        "category": "http",
        "docs_url": "https://www.python-httpx.org",
        "triggers": {"httpx", "async client", "asyncclient"},
    },
    {
        "name": "OpenAI",
        "category": "llm",
        "docs_url": "https://platform.openai.com/docs",
        "triggers": {"openai", "gpt-4", "gpt-3", "chatgpt", "chat completion", "openai api"},
    },
    {
        "name": "Kubernetes",
        "category": "infra",
        "docs_url": "https://kubernetes.io/docs",
        "triggers": {"kubernetes", "kubectl", "k8s", "helm", "pod", "deployment yaml"},
    },
    {
        "name": "Poetry",
        "category": "packaging",
        "docs_url": "https://python-poetry.org/docs",
        "triggers": {"poetry", "pyproject.toml", "poetry add", "poetry install"},
    },
]


# ── Tool implementation ───────────────────────────────────────────────────────


class LibraryDetectionTool(BaseTool[LibraryDetectionInput, LibraryDetectionOutput]):
    """
    Scan a user query and return all engineering libraries it references.

    Detection strategy:
      For each library in the catalogue, check whether any trigger keyword
      appears as a case-insensitive substring in the normalised query.
      Whole-word boundary matching is used where the trigger is a single token
      to avoid false positives (e.g. 'pod' inside 'episode').
    """

    name: ClassVar[str] = "detect_libraries"
    description: ClassVar[str] = (
        "Detect which engineering libraries or tools are mentioned in a user query. "
        "Returns a structured list with library names, categories, and documentation URLs."
    )
    InputSchema: ClassVar[type[BaseModel]] = LibraryDetectionInput
    OutputSchema: ClassVar[type[BaseModel]] = LibraryDetectionOutput

    async def execute(self, inputs: LibraryDetectionInput) -> LibraryDetectionOutput:
        query_lower = inputs.user_query.lower()
        detected: list[DetectedLibrary] = []

        for entry in _LIBRARY_CATALOGUE:
            matched: list[str] = []
            for trigger in entry["triggers"]:
                if self._matches(query_lower, trigger):
                    matched.append(trigger)

            if matched:
                detected.append(
                    DetectedLibrary(
                        name=entry["name"],
                        category=entry["category"],
                        docs_url=entry["docs_url"],
                        matched_keywords=sorted(matched),
                    )
                )

        return LibraryDetectionOutput(
            query=inputs.user_query,
            detected=detected,
            total_detected=len(detected),
        )

    @staticmethod
    def _matches(text: str, trigger: str) -> bool:
        """
        Return True if the trigger appears in text.

        - Multi-word triggers: plain substring match (they're specific enough).
        - Single-word triggers: whole-word boundary match to reduce false positives.
        """
        if " " in trigger or "-" in trigger:
            return trigger in text

        pattern = rf"\b{re.escape(trigger)}\b"
        return bool(re.search(pattern, text))
