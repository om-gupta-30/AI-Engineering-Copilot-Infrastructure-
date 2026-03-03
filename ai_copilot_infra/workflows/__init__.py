"""
workflows — deterministic AI copilot orchestration layer.

Public surface:
  WorkflowState     — shared execution context (Pydantic model)
  WorkflowStep      — abstract base for a single pipeline step
  StepPipeline      — ordered, unconditional step runner
  CopilotWorkflow   — full 6-step copilot pipeline (primary entry point)
"""

from ai_copilot_infra.workflows.base import StepPipeline, WorkflowStep
from ai_copilot_infra.workflows.copilot_workflow import CopilotWorkflow
from ai_copilot_infra.workflows.state import WorkflowState

__all__ = [
    "WorkflowState",
    "WorkflowStep",
    "StepPipeline",
    "CopilotWorkflow",
]
