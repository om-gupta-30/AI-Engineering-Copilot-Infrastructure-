"""
WorkflowState — the single mutable context object that flows through
every step of the CopilotWorkflow pipeline.

Design rules:
  - One instance is created per workflow execution.
  - Steps read from it, write to it, and pass the same instance forward.
  - All fields have safe defaults so any step can be safely read before
    a preceding step has populated it (useful for error-recovery paths).
  - model_config = frozen=False intentionally: steps mutate the state
    in-place rather than creating copies, keeping the flow O(1) in memory.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class WorkflowState(BaseModel):
    """
    Shared execution context for a single copilot workflow run.

    Lifecycle:
        Created  → IntentClassificationStep
                 → LibraryDetectionStep
                 → DocumentationFetchStep
                 → PromptConstructionStep
                 → LLMGenerationStep
                 → PostValidationStep
        Consumed → CopilotWorkflow.run() returns the structured response
    """

    model_config = {"frozen": False}

    # ── Trace ─────────────────────────────────────────────────────────────────
    trace_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier that correlates all log lines for one request.",
    )

    # ── Input ─────────────────────────────────────────────────────────────────
    user_query: str = Field(..., description="Raw query submitted by the user.")

    # ── Step 1: intent classification ─────────────────────────────────────────
    intent: str = Field(
        default="",
        description="Classified intent label (e.g. 'documentation_query').",
    )

    # ── Step 2: library detection ─────────────────────────────────────────────
    detected_libraries: list[str] = Field(
        default_factory=list,
        description="Canonical library names detected in the user query.",
    )

    # ── Step 3: documentation retrieval ──────────────────────────────────────
    retrieved_docs: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of library_name → concatenated documentation text.",
    )

    # ── Step 4: prompt construction ───────────────────────────────────────────
    constructed_prompt: str | None = Field(
        default=None,
        description="Final grounded prompt passed to the LLM.",
    )

    # ── Step 5: LLM generation ────────────────────────────────────────────────
    llm_output: str | None = Field(
        default=None,
        description="Raw text returned by the LLM (or mock).",
    )

    # ── Step 6: post-validation ───────────────────────────────────────────────
    validation_passed: bool = Field(
        default=False,
        description="True when the response meets minimum quality criteria.",
    )
    validation_reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable explanations for each validation failure or warning.",
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def has_docs(self) -> bool:
        """True when at least one library has retrieved documentation."""
        return bool(self.retrieved_docs)

    def docs_as_text(self) -> str:
        """
        Flatten retrieved_docs into a labelled block of text for prompt injection.

        Format per library:
            --- <LibraryName> Docs ---
            <documentation text>
        """
        if not self.retrieved_docs:
            return "No documentation available."

        sections: list[str] = []
        for library, doc_text in self.retrieved_docs.items():
            sections.append(f"--- {library} Docs ---\n{doc_text}")

        return "\n\n".join(sections)
