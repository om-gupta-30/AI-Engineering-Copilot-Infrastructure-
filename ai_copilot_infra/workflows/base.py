"""
Workflow base primitives.

WorkflowStep  — abstract single step that reads/writes a WorkflowState.
StepPipeline  — ordered runner that feeds the same state through every step.

Design:
  - Steps operate on a shared WorkflowState rather than raw dicts, giving
    full type-safety and IDE completion throughout the pipeline.
  - StepPipeline enforces deterministic, unconditional execution order:
    every step always runs, failures surface as exceptions not silent skips.
  - Logging (step start / end / error) is handled centrally in StepPipeline
    so individual steps stay focused on their domain logic only.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from ai_copilot_infra.observability.logger import get_logger
from ai_copilot_infra.workflows.state import WorkflowState

logger = get_logger(__name__)


class WorkflowStep(ABC):
    """
    A single deterministic unit of work in the pipeline.

    Subclasses implement `execute(state)` and declare a human-readable `name`.
    The step receives the shared WorkflowState, mutates the fields it owns,
    and returns the same object to be passed to the next step.
    """

    name: str = "unnamed_step"

    @abstractmethod
    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Perform this step's work on the shared workflow state.

        Args:
            state: The current WorkflowState; mutate the relevant fields.

        Returns:
            The same (mutated) WorkflowState instance.
        """
        ...


class StepPipeline:
    """
    Runs a fixed, ordered list of WorkflowStep instances against a single
    WorkflowState.

    Contract:
      - Steps execute serially in declaration order.
      - No step is ever skipped.
      - If a step raises, the exception propagates immediately (caller decides
        whether to catch and continue or abort).
      - Per-step timing and structured log events are emitted automatically.
    """

    def __init__(self, steps: list[WorkflowStep]) -> None:
        self.steps = steps

    async def run(self, state: WorkflowState) -> WorkflowState:
        """
        Execute all steps in order against the provided state.

        Args:
            state: Initial WorkflowState (user_query already set).

        Returns:
            The fully populated WorkflowState after all steps have run.
        """
        for step in self.steps:
            start = time.perf_counter()
            logger.info("step_start", step=step.name, query_preview=state.user_query[:80])

            try:
                state = await step.execute(state)
                elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
                logger.info("step_end", step=step.name, duration_ms=elapsed_ms)

            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
                logger.error(
                    "step_error",
                    step=step.name,
                    error=str(exc),
                    duration_ms=elapsed_ms,
                    exc_info=True,
                )
                raise

        return state
