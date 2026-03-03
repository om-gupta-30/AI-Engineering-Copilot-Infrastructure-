"""
DocumentationFetchTool — retrieves real-time documentation via Context7Client.

Execution path:
  1. Validate inputs (Pydantic)
  2. Instantiate Context7Client (reads CONTEXT7_BASE_URL from env)
  3. Call Context7Client.fetch_documentation(library_name)
  4. Wrap the returned text in a single DocumentationSection
  5. Truncate to max_length if needed
  6. Return structured DocumentationFetchOutput with is_mock=False

Error handling:
  Any Context7Error subclass is caught, logged, and re-raised as a
  plain RuntimeError so BaseTool.run() can record it in ToolResult.error
  without leaking internal exception types to callers.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from ai_copilot_infra.context.context7_client import (
    Context7Client,
    Context7Error,
)
from ai_copilot_infra.mcp_server.base import BaseTool
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


# ── Schema definitions ────────────────────────────────────────────────────────


class DocumentationFetchInput(BaseModel):
    """Input schema for DocumentationFetchTool."""

    library_name: str = Field(
        ...,
        min_length=1,
        description="Name of the library to fetch documentation for.",
        examples=["FastAPI", "Redis", "Celery"],
    )
    topic: str | None = Field(
        default=None,
        description="Optional topic keyword to filter content (substring match).",
        examples=["routing"],
    )
    max_length: int = Field(
        default=4000,
        ge=100,
        le=20000,
        description="Maximum character length of the returned documentation text.",
    )


class DocumentationSection(BaseModel):
    """A single section of documentation."""

    heading: str
    content: str


class DocumentationFetchOutput(BaseModel):
    """Output schema for DocumentationFetchTool."""

    library_name: str
    canonical_name: str
    docs_url: str = ""
    topic: str | None
    sections: list[DocumentationSection]
    retrieved_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO-8601 UTC timestamp of when documentation was fetched.",
    )
    is_mock: bool = Field(
        default=False,
        description="Always False — documentation is fetched live from Context7.",
    )


# ── Tool implementation ───────────────────────────────────────────────────────


class DocumentationFetchTool(BaseTool[DocumentationFetchInput, DocumentationFetchOutput]):
    """
    Fetch real-time documentation for a named library via Context7.

    The tool creates a Context7Client per execution — clients are stateless
    and lightweight (no persistent connection). Pass a pre-built client via
    the constructor to inject a test double.
    """

    name: ClassVar[str] = "fetch_documentation"
    description: ClassVar[str] = (
        "Retrieve live documentation text for a named engineering library via Context7. "
        "Returns the content as structured sections ready for LLM prompt injection."
    )
    InputSchema: ClassVar[type[BaseModel]] = DocumentationFetchInput
    OutputSchema: ClassVar[type[BaseModel]] = DocumentationFetchOutput

    def __init__(self, context7_client: Context7Client | None = None) -> None:
        self._client = context7_client

    async def execute(self, inputs: DocumentationFetchInput) -> DocumentationFetchOutput:
        client = self._client or Context7Client()

        logger.info(
            "documentation_fetch_tool_start",
            library=inputs.library_name,
            topic=inputs.topic,
            max_length=inputs.max_length,
        )

        try:
            raw_text = await client.fetch_documentation(inputs.library_name)
        except Context7Error as exc:
            logger.error(
                "documentation_fetch_tool_error",
                library=inputs.library_name,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise RuntimeError(
                f"Failed to fetch documentation for '{inputs.library_name}': {exc}"
            ) from exc

        processed_text = self._apply_topic_filter(raw_text, inputs.topic)
        processed_text = self._truncate(processed_text, inputs.max_length)

        logger.info(
            "documentation_fetch_tool_complete",
            library=inputs.library_name,
            content_length=len(processed_text),
            topic_filtered=inputs.topic is not None,
        )

        return DocumentationFetchOutput(
            library_name=inputs.library_name,
            canonical_name=inputs.library_name,
            topic=inputs.topic,
            sections=[
                DocumentationSection(
                    heading=inputs.library_name,
                    content=processed_text,
                )
            ],
            is_mock=False,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _apply_topic_filter(text: str, topic: str | None) -> str:
        """
        If a topic is specified, retain only the paragraphs / lines that
        contain the topic keyword (case-insensitive). Falls back to the
        full text when no paragraph matches, rather than returning empty.
        """
        if not topic:
            return text

        topic_lower = topic.lower()
        paragraphs = text.split("\n\n")
        matched = [p for p in paragraphs if topic_lower in p.lower()]

        return "\n\n".join(matched) if matched else text

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Hard-truncate text to max_length characters with a visible marker."""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "\n… [truncated]"
