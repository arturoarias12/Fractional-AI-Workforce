"""Framework-neutral graph contracts.

Import :mod:`graph.production` only when the optional LangGraph dependency is
installed.
"""

from .state import TraderBranchState, WorkflowInput, WorkflowState
from .workflow import WorkflowBlueprint, planned_workflow

__all__ = [
    "TraderBranchState",
    "WorkflowInput",
    "WorkflowBlueprint",
    "WorkflowState",
    "planned_workflow",
]
