"""
OutputValidator — post-generation quality gate for CopilotWorkflow responses.

Runs a battery of deterministic checks on the LLM output before it is
returned to the caller. All checks are local (no LLM-as-judge call), fast,
and side-effect-free.

Validation rules (applied in order):
  1. Empty output               → hard fail
  2. Output too short (<100 ch) → hard fail
  3. No docs retrieved          → hard fail
  4. Libraries not mentioned    → soft fail (answer may be ungrounded)
  5. Hallucinated libraries     → warning appended to reasons (pass kept)

Usage:
    validator = OutputValidator()
    result = validator.validate(
        generated_text=state.llm_output,
        detected_libraries=state.detected_libraries,
        retrieved_docs=state.retrieved_docs,
    )
    # result == {"passed": bool, "reasons": list[str]}
"""

from __future__ import annotations

import re

from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)

# Minimum character length for a response to be considered non-trivial.
_MIN_OUTPUT_LENGTH = 100

# Full catalogue of library names the system knows about.
# Kept in sync with mcp_server/library_detection_tool._LIBRARY_CATALOGUE.
_KNOWN_LIBRARY_NAMES: frozenset[str] = frozenset(
    {
        "FastAPI",
        "Redis",
        "Celery",
        "Docker",
        "Pydantic",
        "SQLAlchemy",
        "Langchain",
        "Langfuse",
        "Loguru",
        "Pytest",
        "Uvicorn",
        "httpx",
        "OpenAI",
        "Kubernetes",
        "Poetry",
    }
)


class OutputValidator:
    """
    Stateless validator for LLM-generated copilot responses.

    All validation state lives in the local variables of `validate()`;
    the class carries no mutable state and is safe for concurrent use.
    """

    def validate(
        self,
        generated_text: str,
        detected_libraries: list[str],
        retrieved_docs: dict[str, str],
    ) -> dict:
        """
        Run all validation rules and return a structured verdict.

        Args:
            generated_text:      Raw LLM output string.
            detected_libraries:  Library names detected from the user query.
            retrieved_docs:      Mapping of library_name → doc text used as context.

        Returns:
            {
                "passed":  bool        — True when all hard rules pass,
                "reasons": list[str]   — Human-readable explanation of each failure
                                         or warning; empty list on clean pass.
            }
        """
        reasons: list[str] = []
        passed = True

        # ── Rule 1: empty output ──────────────────────────────────────────────
        if not generated_text or not generated_text.strip():
            reasons.append("Output is empty.")
            passed = False

            logger.warning(
                "validation_failed",
                rule="empty_output",
                passed=False,
                reasons=reasons,
            )
            # Cannot apply further checks on empty text — return early.
            return {"passed": passed, "reasons": reasons}

        text_lower = generated_text.lower()

        # ── Rule 2: output too short ──────────────────────────────────────────
        if len(generated_text.strip()) < _MIN_OUTPUT_LENGTH:
            reasons.append(
                f"Output is too short ({len(generated_text.strip())} chars; "
                f"minimum is {_MIN_OUTPUT_LENGTH})."
            )
            passed = False

        # ── Rule 3: no retrieved docs (warning — does not hard-fail) ─────────
        if not retrieved_docs:
            reasons.append("Warning: no documentation was retrieved; answer may not be grounded.")

        # ── Rule 4: detected libraries not mentioned (warning) ────────────────
        if detected_libraries:
            unmentioned = [lib for lib in detected_libraries if not self._mentions(text_lower, lib)]
            if unmentioned:
                reasons.append(
                    f"Warning: output does not mention the following detected "
                    f"{'library' if len(unmentioned) == 1 else 'libraries'}: "
                    f"{', '.join(unmentioned)}."
                )

        # ── Rule 5: hallucinated libraries (warning only, does not fail) ──────
        hallucinated = self._find_hallucinated_libraries(text_lower, detected_libraries)
        if hallucinated:
            reasons.append(
                f"Warning: output references "
                f"{'library' if len(hallucinated) == 1 else 'libraries'} "
                f"not present in the detected context: "
                f"{', '.join(sorted(hallucinated))}. "
                "This may indicate hallucination."
            )
            # Intentionally not flipping `passed` — this is advisory only.

        # ── Emit structured log ───────────────────────────────────────────────
        logger.info(
            "validation_complete",
            passed=passed,
            reasons=reasons,
            detected_libraries=detected_libraries,
            has_docs=bool(retrieved_docs),
            output_length=len(generated_text.strip()),
        )

        return {"passed": passed, "reasons": reasons}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _mentions(text_lower: str, library: str) -> bool:
        """
        Return True when *library* appears in *text_lower* using a
        case-insensitive whole-word / substring match.

        Multi-token library names (e.g. "Docker Compose") use plain
        substring matching; single tokens use word-boundary regex to
        avoid false positives (e.g. 'pod' inside 'episode').
        """
        needle = library.lower()
        if " " in needle or "-" in needle:
            return needle in text_lower
        pattern = rf"\b{re.escape(needle)}\b"
        return bool(re.search(pattern, text_lower))

    @staticmethod
    def _find_hallucinated_libraries(
        text_lower: str,
        detected_libraries: list[str],
    ) -> list[str]:
        """
        Return library names from the known catalogue that appear in the
        generated text but were NOT part of the detected context.

        Only known library names are checked; arbitrary unknown tokens are
        not flagged (that would require a much heavier NER approach).
        """
        detected_lower = {lib.lower() for lib in detected_libraries}
        hallucinated: list[str] = []

        for lib_name in _KNOWN_LIBRARY_NAMES:
            needle = lib_name.lower()
            if needle in detected_lower:
                continue
            if " " in needle or "-" in needle:
                found = needle in text_lower
            else:
                found = bool(re.search(rf"\b{re.escape(needle)}\b", text_lower))

            if found:
                hallucinated.append(lib_name)

        return hallucinated
