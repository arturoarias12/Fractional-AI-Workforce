"""Framework-neutral agent lifecycle records used by orchestration and UI."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr


LIFECYCLE_SCHEMA_VERSION = "0.1.0"


class AgentExecutionState(StrEnum):
    """Common lifecycle shared by every hireable agent."""

    IDLE = "idle"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_REVIEW = "waiting_for_review"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentLifecycleRecord(ContractModel):
    """Checkpoint-safe status record matching the team State Graph schema."""

    schema_version: NonEmptyStr = LIFECYCLE_SCHEMA_VERSION
    agent_name: NonEmptyStr
    current_state: AgentExecutionState
    current_task: NonEmptyStr | None = None
    input: dict[str, Any] | NonEmptyStr | None = None
    output: dict[str, Any] | NonEmptyStr | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    next_step: NonEmptyStr | None = None
    error_message: NonEmptyStr | None = None
    additional_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_temporal_and_terminal_fields(self) -> "AgentLifecycleRecord":
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time < self.start_time
        ):
            raise ValueError("end_time cannot precede start_time.")
        if (
            self.current_state is AgentExecutionState.FAILED
            and self.error_message is None
        ):
            raise ValueError("A failed lifecycle record requires error_message.")
        if (
            self.current_state is AgentExecutionState.COMPLETED
            and self.end_time is None
        ):
            raise ValueError("A completed lifecycle record requires end_time.")
        return self


__all__ = [
    "AgentExecutionState",
    "AgentLifecycleRecord",
    "LIFECYCLE_SCHEMA_VERSION",
]
